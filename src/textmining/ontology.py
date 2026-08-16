import obonet
import networkx as nx
import math
from collections import defaultdict
import re
import tempfile
from pathlib import Path
import logging
import time
import rustworkx as rx
from typing import Iterator, Iterable
import io
import urllib.request

logger = logging.getLogger(__name__)

def to_external_id(term_id: str) -> str:
    if ":" not in term_id:
        return term_id
    prefix, local_id = term_id.split(":", 1)
    return f"{prefix}_{local_id}"

def to_internal_id(term_id: str) -> str:
    if ":" in term_id:
        return term_id
    if "_" not in term_id:
        return term_id
    prefix, local_id = term_id.split("_", 1)
    return f"{prefix}:{local_id}"

def get_exact_synonyms(node_data: dict):
    exact_syns = []
    for s in node_data.get("synonym", []):
        parts = s.split('"')
        
        if len(parts) > 2:
            text = parts[1]
            scope_parts = parts[2].strip().split()
            if not scope_parts:  # no scope word present, skip
                continue
            scope = scope_parts[0]  # EXACT / RELATED / BROAD / NARROW
            if scope == "EXACT":
                exact_syns.append(text)
    return exact_syns

def _process_obo_lines(lines: Iterable[str], ignore_obsolete: bool, exclude_gci: bool):
    cleaned_lines = []
    for line in lines:
        if exclude_gci:
            stripped = line.lstrip()
            is_gci_is_a = (
                stripped.startswith("is_a:")
                and ("gci_filler=" in stripped or "gci_relation=" in stripped)
            )
            if is_gci_is_a:
                continue
        cleaned_lines.append(line)
            
    obo_stream = io.StringIO("".join(cleaned_lines))
    return obonet.read_obo(obo_stream, ignore_obsolete=ignore_obsolete)


def read_obo(
    source: str | Path,
    ignore_obsolete: bool = True,
    exclude_gci: bool = False,
    from_url: bool = False
):
    source = str(source)
    if from_url:
        req = urllib.request.Request(
            source, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req) as response:
            with io.TextIOWrapper(response, encoding="utf-8") as text_stream:
                return _process_obo_lines(text_stream, ignore_obsolete, exclude_gci)
    else:
        with Path(source).open("r", encoding="utf-8") as f:
            return _process_obo_lines(f, ignore_obsolete, exclude_gci)
        

class OntologyGraph:
    
    def __init__(self,
                 graph: rx.PyDiGraph, 
                 relationship: str):
        self.graph = graph
        self.relationship = relationship
        graph_name = graph.attrs.get('name', '')
        
        t0 = time.monotonic()
        logger.info("Parsed ontology graph: %s", graph_name)
        
        self._rel_subgraph = OntologyGraph.build_relationship_subgraph(self.graph, self.relationship)
        if not rx.is_directed_acyclic_graph(self._rel_subgraph):
            logger.critical("Relationship subgraph for %s is not a DAG", graph_name)
            raise RuntimeError("LCA only defined on directed acyclic graphs.")
        if len(self._rel_subgraph) == 0:
            logger.error("Relationship subgraph for %s is empty", graph_name)
            raise RuntimeError("Meaningless null graph.")
        logger.debug("Built relationship subgraph for %s (%d nodes)", graph_name, len(self._rel_subgraph)) 
        self.roots = self.find_roots()
        logger.debug("Found %d root(s) for %s", len(self.roots), graph_name)
        
        self._id_to_idx = {
            data["id"]: idx 
            for idx, data in enumerate(self.graph.nodes())
            if "id" in data
        }
        self._alt_id_to_idx = OntologyGraph._build_alt_id_map(self._rel_subgraph)
        logger.debug("Built alt-id map for %s (%d entries)", graph_name, len(self._alt_id_to_idx))
                
        self._ancestor_cache = {}
        self._descendant_count_cache = {}
        self._depths = self._compute_depths()
        self.node_num = self._rel_subgraph.num_nodes()
        
        logger.info("Initialized ontology graph %s: %d nodes, %d roots, %.2fs",
            graph_name, self.node_num, len(self.roots), time.monotonic() - t0)
        
    @classmethod
    def from_obo(cls, 
                 obo_path: str | Path, 
                 relatioship: str = 'is_a',
                 exclude_gci: bool = False,
                 ignore_obsolete: bool = True):
        
        nx_graph = read_obo(source=obo_path,
                            ignore_obsolete=ignore_obsolete,
                            exclude_gci=exclude_gci,
                            from_url=False)
        return cls.from_nx_graph(nx_graph=nx_graph,
                                 relationship=relatioship,
                                 name=obo_path)
        
    @classmethod
    def from_merge(cls, obo_paths, equivalence_fn, relationship='is_a'):
        raise NotImplementedError('Merging not implemented yet.')

    @classmethod
    def from_dict(cls, 
                  edges: tuple | list,
                  nodes: dict, 
                  relationship: str = 'is_a', 
                  name: str = ''):
        g = rx.PyDiGraph(attrs={'name': name})
        
        # Add nodes
        term_id_to_idx = {}
        if isinstance(nodes, dict):
            for node_id, attrs in nodes.items():
                if attrs is None:
                    attrs = {}
                elif not isinstance(attrs, dict):
                    raise TypeError(f"Node attributes for {node_id} must be a dict, got {type(attrs)}")
                payload = {"id": node_id, **attrs}
                graph_idx = g.add_node(payload)
                term_id_to_idx[node_id] = graph_idx
        else:
            raise TypeError("nodes must be a dict mapping node_id -> attribute dict")
        
        # Add edges
        for edge in edges:
            if not isinstance(edge, (tuple, list)):
                raise TypeError(f"Edge must be tuple/list, got {type(edge)}: {edge}")
            
            if len(edge) == 3:
                u, v, k = edge
                data = {}
            elif len(edge) == 4:
                u, v, k, data = edge
                if data is None:
                    data = {}
                elif not isinstance(data, dict):
                    raise TypeError(f"Edge data must be a dict, got {type(data)} for edge {edge}")
            else:
                raise ValueError(
                    "Each edge must be (u, v, key) or (u, v, key, data_dict)"
                )
            
            if u not in term_id_to_idx:
                graph_idx = g.add_node(u)
                term_id_to_idx[u] = graph_idx
            if v not in term_id_to_idx:
                graph_idx = g.add_node(v)
                term_id_to_idx[v] = graph_idx
            
            edge_payload = {"key": k, **data}
            g.add_edge(term_id_to_idx[u], term_id_to_idx[v], edge_payload)
        return cls(g, relationship)
    
    @classmethod
    def from_url(cls, 
                 url : str,
                 relationship: str = 'is_a',
                 exclude_gci: bool = False,
                 ignore_obsolete: bool = True):
        nx_graph = read_obo(
            source=url,
            ignore_obsolete=ignore_obsolete,
            exclude_gci=exclude_gci,
            from_url=True
        )
        return cls.from_nx_graph(
            nx_graph=nx_graph,
            relationship=relationship,
            name=url
        )
    
    @classmethod
    def from_nx_graph(cls, 
                      nx_graph: nx.MultiDiGraph,
                      relationship: str = 'is_a',
                      name: str = 'unknown'):
        for node_id, data in nx_graph.nodes(data=True):
            data['id'] = node_id
        for _, _, key, data in nx_graph.edges(keys=True, data=True):
            data['key'] = key
        rx_graph = rx.networkx_converter(nx_graph, keep_attributes=True)
        rx_graph.attrs = {
            'name':
                getattr(nx_graph, 'name', name)
        }
        return cls(rx_graph, relationship)
        
    @staticmethod
    def _build_alt_id_map(graph: rx.PyDiGraph):        
        alt_id_to_idx = {}
        nodes_with_data = [(idx, graph[idx]) for idx in graph.node_indices()]
        for idx, data in nodes_with_data:
            for alt in data.get("alt_id", []):
                alt_id_to_idx[alt] = idx
        return alt_id_to_idx
    
    @staticmethod
    def build_relationship_subgraph(graph: rx.PyDiGraph, 
                                    relationship: str):
        rel_subgraph = rx.PyDiGraph(multigraph=True)
        
        rel_subgraph.add_nodes_from(graph.nodes())

        kept_edges = [
            (u, v, data) for u, v, data in graph.weighted_edge_list() 
            if data['key'] == relationship
        ]
        rel_subgraph.add_edges_from([(v, u, data) for u, v, data in kept_edges])

        return rel_subgraph

    def find_roots(self):
        g = self._rel_subgraph
        return {idx for idx in g.node_indices() if g.in_degree(idx) == 0}
        
    def _compute_depths(self):
        depths = {}
        g = self._rel_subgraph
        
        for idx in rx.topological_sort(g):
            parents = g.predecessor_indices(idx)
            depths[idx] = 0 if not parents else 1 + max(depths[p] for p in parents)
        return depths
    
    def ancestors(self, idx: int) -> set:
        if idx not in self._ancestor_cache:
            if not self._rel_subgraph.has_node(idx):
                logger.error("Can not compute ancestors for unknown index: %d", idx)
                raise ValueError(f"Can not compute ancestors for unknown index: {idx}")
            self._ancestor_cache[idx] = rx.ancestors(self._rel_subgraph, idx)
        return self._ancestor_cache[idx]

    def ancestor_closure(self, indices: Iterator[int]) -> set:
        keep = set()
        for idx in indices:
            if not self._rel_subgraph.has_node(idx):
                logger.error('Can not compute ancestor closure for unknown index: %s', idx)
                raise ValueError(f'Can not compute ancestor closure for unknown index: {idx}')
            keep.add(idx)
            keep.update(rx.ancestors(self._rel_subgraph, idx))
        return keep
    
    def induced_subgraph(self, indices, as_ontology_graph=False):
        keep = self.ancestor_closure(indices)
        sub = self.graph.subgraph(keep, preserve_attrs=True).copy()
        if as_ontology_graph:
            return OntologyGraph(sub, self.relationship)
        return sub
    
    def find_lca(self, *term_ids):
        term_ids_internal = [to_internal_id(t) for t in term_ids]
        indices = self.map_to_indices(term_ids_internal)
        common_ancestors_indices = set.intersection(*[self.ancestors(idx) | {idx} for idx in indices])
        if not common_ancestors_indices:
            return None
        
        max_depth = max(self._depths[a] for a in common_ancestors_indices)
        lca_indices = [a for a in common_ancestors_indices if self._depths[a] == max_depth]
        
        if len(lca_indices) == 1:
            return self.map_idx_to_external_id(lca_indices[0]) 
        
        return max(map(self.map_idx_to_external_id, lca_indices), key=lambda idx: (self._compute_ic_from_index(idx), idx))
        
        
    def compute_ic(self, term_id):
        return self._compute_ic_from_index(self.map_to_index(term_id))
    
    def _compute_ic_from_index(self, idx):
        if idx not in self._descendant_count_cache:
            if not self._rel_subgraph.has_node(idx):
                logger.error('Unknown index for IC computation: %d', idx)
                raise ValueError(f'Unknown term idx: {idx}')
            self._descendant_count_cache[idx] = len(rx.descendants(self._rel_subgraph, idx)) + 1
        count = self._descendant_count_cache[idx]
        return -math.log(count / self.node_num)
    
    # Need to be internal ids
    def map_to_indices(self, term_ids):
        out = []
        for term_id in term_ids:
            idx = self.map_to_index(term_id)
            out.append(idx)
        return out
    
    # Needs to be internal id
    def map_to_index(self, term_id):
        idx = self._id_to_idx.get(term_id, None)
        if idx is None:
            logger.error('Can not map unknown term_id to index: %s', term_id)
            raise ValueError(f'Can not map unknown term_id to index: {term_id}')
        return idx
    
    def map_idx_to_external_id(self, idx):
        if not self._rel_subgraph.has_node(idx):
            logger.error('Index %d not in graph', idx)
            raise ValueError(f'Index {idx} not in graph')
        data = self._rel_subgraph.get_node_data(idx)
        return to_external_id(data['id'])
    
    def resolve_id(self, term_id) -> str:
        internal_id = to_internal_id(term_id)
        idx = self._id_to_idx.get(internal_id, None)
        if idx is not None:
            return term_id
        alt_idx = self._alt_id_to_idx.get(internal_id, None)
        external_id = None
        if alt_idx is not None:
            data = self._rel_subgraph.get_node_data(alt_idx)
            external_id = to_external_id(data['id'])
        return external_id
    
    # Root ids in internal format
    def extract_synonyms(self,
                         root_ids: Iterator[str] | None = None) -> Iterator[tuple[str, list[str]]]:
        indices = self._rel_subgraph.node_indices()
        if root_ids:
            indices = set.union({
                rx.descendants(self._id_to_idx[root_id] for root_id in root_ids)
                })

        for idx in indices:
            data = self._rel_subgraph[idx]
            name = data.get("name") if data else None
            term_id = data.get("id") if data else None
            if not (data and name and term_id):
                continue
            syns = [name]
            exact_syns = get_exact_synonyms(data)
            if exact_syns:
                syns.extend(exact_syns)
            syns = list(set(syns))
            term_id_external = to_external_id(term_id)
            yield (term_id_external, syns)
            
    
