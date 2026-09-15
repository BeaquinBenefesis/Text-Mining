import obonet
import networkx as nx
import math
import pickle
from pathlib import Path
import logging
import time
import rustworkx as rx
from typing import Iterator, Iterable
import io
import re
import urllib.request
import hashlib

logger = logging.getLogger(__name__)

def to_external_id(term_id: str) -> str:
    if ":" not in term_id:
        return term_id
    prefix, local_id = term_id.split(":", 1)
    return f"{prefix}_{local_id}"

def normalize_root_ids(root_ids: Iterable[str] | None) -> tuple[str, ...] | None:
    """Canonical form for a root set: internal ids, deduplicated, sorted. None and
    empty both mean 'unrestricted', so they compare equal."""
    if not root_ids:
        return None
    return tuple(sorted({to_internal_id(r) for r in root_ids}))

def normalize_relationships(relationships: str | Iterable[str]) -> tuple[str, ...]:
    """Canonical form for a relationship set: a plain string is one relationship;
    otherwise deduplicated and sorted, so ('part_of', 'is_a') == ('is_a', 'part_of')."""
    if isinstance(relationships, str):
        return (relationships,)
    normalized = tuple(sorted(set(relationships)))
    if not normalized:
        raise ValueError("At least one relationship type is required")
    return normalized

def to_internal_id(term_id: str) -> str:
    if ":" in term_id:
        return term_id
    if "_" not in term_id:
        return term_id
    prefix, local_id = term_id.split("_", 1)
    return f"{prefix}:{local_id}"

ABBREVIATION_TAGS = {"ABBREVIATION", "OMO:0003012", "OMO:0003000"}

OBO_SYNONYM_RE = re.compile(
    r'^\s*"((?:[^"\\]|\\.)*)"\s+(EXACT|RELATED|BROAD|NARROW)(?:\s+([^\s\[]+))?'
)

def get_exact_synonyms(node_data: dict) -> tuple[list[str], list[str]]:
    """EXACT-scope synonyms for a node, split into (synonyms, abbreviations)
    by the OBO synonym TYPE field (e.g. "ABBREVIATION") or abbreviation detection criteria."""
    syns, abbrevs = [], []
    for s in node_data.get("synonym", []):
        match = OBO_SYNONYM_RE.match(s)
        if not match:
            continue
        text, scope, syn_type = match.groups()
        if scope != "EXACT":
            continue
        text = text.replace(r'\"', '"')
        (abbrevs if syn_type in ABBREVIATION_TAGS or (text != node_data.get("name") and probable_abbreviation(text)) else syns).append(text)
    return syns, abbrevs

def probable_abbreviation(term: str) -> bool:
    upper_count = sum(1 for char in term if char.isupper())
    alpha_count = len([c for c in term if c.isalpha()])
    return len(term) <= 8 and " " not in term and upper_count >= 2 and (upper_count / alpha_count) >= 0.5

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
):
    with Path(source).open("r", encoding="utf-8") as f:
        return _process_obo_lines(f, ignore_obsolete, exclude_gci)
        

class OntologyGraph:

    source_hash: str | None = None
    # Class-level default so pickles built before root restriction existed load
    # with root_ids = None, which is exactly what they are: unrestricted.
    root_ids: tuple[str, ...] | None = None
    # Same idea: pickles from before multi-relationship support were all is_a-only.
    relationships: tuple[str, ...] = ('is_a',)

    def __init__(self,
                 graph: rx.PyDiGraph,
                 relationships: str | Iterable[str] = 'is_a',
                 root_ids: Iterable[str] | None = None):
        graph_name = graph.attrs.get('name', '')
        t0 = time.monotonic()
        logger.info("Parsed ontology graph: %s", graph_name)

        # Restrict first: everything below (_id_to_idx from self.graph, ancestors/IC
        # from _rel_subgraph) assumes both share one contiguous index space.
        self.root_ids = normalize_root_ids(root_ids)
        self.relationships = normalize_relationships(relationships)
        if self.root_ids:
            n_before = graph.num_nodes()
            graph = OntologyGraph.restrict_to_roots(graph, self.relationships, self.root_ids)
            logger.info("Restricted %s to %d root(s) over %s: %d -> %d nodes",
                        graph_name, len(self.root_ids), '+'.join(self.relationships),
                        n_before, graph.num_nodes())
        self.graph = graph

        self._rel_subgraph = OntologyGraph.build_relationship_subgraph(self.graph, self.relationships)
        if not rx.is_directed_acyclic_graph(self._rel_subgraph):
            logger.critical("Relationship subgraph for %s is not a DAG", graph_name)
            raise RuntimeError("LCA only defined on directed acyclic graphs.")
        if len(self._rel_subgraph) == 0:
            logger.error("Relationship subgraph for %s is empty", graph_name)
            raise RuntimeError("Meaningless null graph.")
        logger.debug("Built relationship subgraph for %s (%d nodes)", graph_name, len(self._rel_subgraph)) 
        self.roots = self.find_roots()
        logger.debug("Found %d root(s) for %s", len(self.roots), graph_name)
        
        self._id_to_idx = {data["id"]: idx for idx, data in zip(self.graph.node_indices(), self.graph.nodes())}
        if self.root_ids:
            found = {self._rel_subgraph[idx]["id"] for idx in self.roots}
            if found != set(self.root_ids):
                logger.critical("Roots of restricted %s are %s, expected %s",
                                graph_name, sorted(found), list(self.root_ids))
                raise RuntimeError(f"Root restriction produced unexpected roots for {graph_name}")
        self._alt_id_to_idx = OntologyGraph._build_alt_id_map(self._rel_subgraph)
        logger.debug("Built alt-id map for %s (%d entries)", graph_name, len(self._alt_id_to_idx))
                
        self._ancestor_cache = {}
        self._descendant_count_cache = {}
        self._depths = self._compute_depths()
        self.node_num = self._rel_subgraph.num_nodes()
        
        logger.info("Initialized ontology graph %s: %d nodes, %d roots, %.2fs",
            graph_name, self.node_num, len(self.roots), time.monotonic() - t0)

    def save(self, path: str | Path):
        t0 = time.monotonic()
        with Path(path).open('wb') as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)
        logger.info("Saved ontology graph %s to %s (%.2fs)",
            self.graph.attrs.get('name', ''), path, time.monotonic() - t0)

    @classmethod
    def load(cls, path: str | Path) -> 'OntologyGraph':
        t0 = time.monotonic()
        with Path(path).open('rb') as f:
            obj = pickle.load(f)
        if not isinstance(obj, cls):
            raise TypeError(f"{path} does not contain an OntologyGraph")
        logger.info("Loaded ontology graph %s from %s (%.2fs)",
            obj.graph.attrs.get('name', ''), path, time.monotonic() - t0)
        return obj

    @classmethod
    def from_obo(cls,
                 obo_path: str | Path,
                 relationships: str | Iterable[str] = 'is_a',
                 exclude_gci: bool = False,
                 ignore_obsolete: bool = True,
                 root_ids: Iterable[str] | None = None):
        nx_graph = read_obo(source=obo_path,
                            ignore_obsolete=ignore_obsolete,
                            exclude_gci=exclude_gci,)
        graph = cls.from_nx_graph(nx_graph=nx_graph,
                                 relationships=relationships,
                                 name=obo_path,
                                 root_ids=root_ids)
        graph.source_hash = hashlib.sha256(Path(obo_path).read_bytes()).hexdigest()

        return graph

    @classmethod
    def from_source(cls, source) -> 'OntologyGraph':
        """Load an OntologySource (resources.py): the pickle cache if it was built
        with the same roots and relationships, otherwise parse the .obo in memory.
        The cache is not rewritten here -- refresh_data.py owns it."""
        if source.cache_path and source.cache_path.exists():
            cached = cls.load(source.cache_path)
            if cached.built_with(source.roots, source.relationships):
                return cached
            logger.warning("%s: cache %s was built with roots %s over %s, expected roots %s over %s; "
                           "parsing %s instead (run scripts/pipeline/refresh_data.py to update the cache)",
                           source.hit_type.name, source.cache_path, cached.root_ids, cached.relationships,
                           normalize_root_ids(source.roots), normalize_relationships(source.relationships),
                           source.local_path)
        return cls.from_obo(obo_path=source.local_path, relationships=source.relationships,
                            root_ids=source.roots, **source.obo_kwargs)

    def built_with(self, root_ids: Iterable[str] | None, relationships: str | Iterable[str]) -> bool:
        return (self.root_ids == normalize_root_ids(root_ids)
                and self.relationships == normalize_relationships(relationships))
        
    @classmethod
    def from_merge(cls, obo_paths, equivalence_fn, relationships='is_a'):
        raise NotImplementedError('Merging not implemented yet.')

    @classmethod
    def from_dict(cls, 
                  edges: tuple | list,
                  nodes: dict, 
                  relationships: str | Iterable[str] = 'is_a', 
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
                graph_idx = g.add_node({"id": u})
                term_id_to_idx[u] = graph_idx
            if v not in term_id_to_idx:
                graph_idx = g.add_node({"id": v})
                term_id_to_idx[v] = graph_idx
            
            edge_payload = {"key": k, **data}
            g.add_edge(term_id_to_idx[u], term_id_to_idx[v], edge_payload)
        return cls(g, relationships)
    
    @classmethod
    def from_nx_graph(cls, 
                      nx_graph: nx.MultiDiGraph,
                      relationships: str | Iterable[str] = 'is_a',
                      name: str = 'unknown',
                      root_ids: Iterable[str] | None = None):
        for node_id, data in nx_graph.nodes(data=True):
            data['id'] = node_id
        for _, _, key, data in nx_graph.edges(keys=True, data=True):
            data['key'] = key
        rx_graph = rx.networkx_converter(nx_graph, keep_attributes=True)
        rx_graph.attrs = {
            'name':
                getattr(nx_graph, 'name', name)
        }
        return cls(rx_graph, relationships, root_ids=root_ids)

    @staticmethod
    def restrict_to_roots(graph: rx.PyDiGraph,
                          relationships: str | Iterable[str],
                          root_ids: Iterable[str]) -> rx.PyDiGraph:
        """Induced subgraph over the roots and their descendants along any of `relationships`.
        Other edge types among kept nodes survive; edges to dropped nodes do not.

        Uses subgraph(), which renumbers indices contiguously. remove_nodes_from()
        would leave gaps, and build_relationship_subgraph re-adds nodes from 0, so the
        edges would silently attach to the wrong nodes."""
        rel_subgraph = OntologyGraph.build_relationship_subgraph(graph, relationships)
        id_to_idx = {data["id"]: idx for idx, data in zip(graph.node_indices(), graph.nodes())}
        missing = [r for r in root_ids if r not in id_to_idx]
        if missing:
            logger.error("Root id(s) not in graph %s: %s", graph.attrs.get('name', ''), missing)
            raise ValueError(f"Root id(s) not in graph: {missing}")
        keep = set()
        for root_id in root_ids:
            root_idx = id_to_idx[root_id]
            keep.add(root_idx)
            keep.update(rx.descendants(rel_subgraph, root_idx))
        return graph.subgraph(sorted(keep), preserve_attrs=True)

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
                                    relationships: str | Iterable[str]):
        """Parent -> child graph over the edges whose key is one of `relationships`.
        A pair linked by several kept relationships gets parallel edges; ancestors,
        descendants, depths and the in-degree root test are unaffected by that."""
        keys = set(normalize_relationships(relationships))
        rel_subgraph = rx.PyDiGraph(multigraph=True)
        
        rel_subgraph.add_nodes_from(graph.nodes())

        kept_edges = [
            (u, v, data) for u, v, data in graph.weighted_edge_list() 
            if data['key'] in keys
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
            return OntologyGraph(sub, self.relationships)
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
        
        max_lca_idx = max(lca_indices, key=lambda idx: (self.compute_ic_from_index(idx), idx))
        return self.map_idx_to_external_id(max_lca_idx)
        
        
    def compute_ic(self, term_id):
        return self.compute_ic_from_index(self.map_to_index(term_id))
    
    def compute_ic_from_index(self, idx):
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
            return to_external_id(term_id)
        alt_idx = self._alt_id_to_idx.get(internal_id, None)
        external_id = None
        if alt_idx is not None:
            data = self._rel_subgraph.get_node_data(alt_idx)
            external_id = to_external_id(data['id'])
        return external_id
    
    def iter_nodes(self, root_ids: Iterator[str] | None = None) -> Iterator:
        indices = self.calculate_descendant_closure(root_ids) if root_ids else self._rel_subgraph.node_indices()
        return (self._rel_subgraph[idx] for idx in indices)
    
    # Root ids in internal format
    def extract_synonyms(self,
                         root_ids: Iterator[str] | None = None) -> Iterator[tuple[str, list[str], list[str]]]:
        """Yields (term_id, synonyms, abbreviations) per term. `synonyms`
        always includes the term's name; `abbreviations` is [] for terms
        with none."""
        indices = self._rel_subgraph.node_indices()
        if root_ids:
            indices = self.calculate_descendant_closure(root_ids)

        results = []
        for idx in indices:
            data = self._rel_subgraph[idx]
            name = data.get("name") if data else None
            term_id = data.get("id") if data else None
            if not (data and name and term_id):
                continue
            exact_syns, abbrevs = get_exact_synonyms(data)
            syns = sorted({name, *exact_syns})
            abbrevs = sorted(set(abbrevs))
            term_id_external = to_external_id(term_id)
            results.append((term_id_external, syns, abbrevs))

        results.sort(key=lambda triple: triple[0])
        yield from results
    
    def calculate_descendant_closure(self, root_ids: Iterator[str]):
        indices = set()
        if root_ids:
            for root_id in root_ids:
                root_idx = self._id_to_idx[root_id]
                indices.update(rx.descendants(self._rel_subgraph, root_idx) | {root_idx})
        return indices

    
