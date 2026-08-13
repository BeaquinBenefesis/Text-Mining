import obonet
import networkx as nx
import math
from collections import defaultdict
import re
import tempfile
from pathlib import Path
import logging
import time

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

def read_obo_without_gci_is_a(obo_path):
    obo_path = Path(obo_path)
    with obo_path.open("r", encoding="utf-8") as f:
        cleaned_lines = []
        for line in f:
            stripped = line.lstrip()
            is_gci_is_a = (
                stripped.startswith("is_a:")
                and ("gci_filler=" in stripped or "gci_relation=" in stripped)
            )
            if is_gci_is_a:
                continue
            cleaned_lines.append(line)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".obo",
        delete=False
    ) as tmp:
        tmp.writelines(cleaned_lines)
        tmp_path = tmp.name
    return obonet.read_obo(tmp_path)

class OntologyGraph:
    
    def __init__(self, graph, relationship):
        self.graph = graph
        self.relationship = relationship
        logger.info("Parsing ontology graph: %s", graph.name)
        t0 = time.monotonic()

        self._alt_id_to_id = OntologyGraph._build_id_map(graph)
        logger.debug("Built alt-id map for %s (%d entries)", graph.name, len(self._alt_id_to_id))

        self._rel_subgraph = OntologyGraph.build_relationship_subgraph(graph, relationship)
        if not nx.is_directed_acyclic_graph(self._rel_subgraph):
            logger.error("Relationship subgraph for %s is not a DAG", graph.name)
            raise nx.NetworkXError("LCA only defined on directed acyclic graphs.")
        if len(self._rel_subgraph) == 0:
            logger.error("Relationship subgraph for %s is empty", graph.name)
            raise nx.NetworkXPointlessConcept("LCA meaningless on null graphs.")
        logger.debug("Built relationship subgraph for %s (%d nodes)", graph.name, len(self._rel_subgraph))

        self.roots = self._find_roots()
        logger.debug("Found %d root(s) for %s", len(self.roots), graph.name)

        self._ancestor_cache = {}
        self._depths = self._compute_depths()
        self._descendant_counts_cache = self._descendant_counts()
        self._node_num = self._rel_subgraph.number_of_nodes()

        logger.info(
            "Initialized ontology graph %s: %d nodes, %d roots, %.2fs",
            graph.name, self._node_num, len(self.roots), time.monotonic() - t0,
        )
    
    @classmethod
    def from_obo(cls, obo_path, relationship='is_a'):
        return cls(read_obo_without_gci_is_a(obo_path), relationship)
    
    @classmethod
    def from_merge(cls, obo_paths, equivalence_fn, relationship='is_a'):
        return cls(cls.merge_ontologies(obo_paths, equivalence_fn), relationship)
    
    @classmethod
    def from_dict(cls, edges, nodes, relationship='is_a'):
        g = nx.MultiDiGraph()

        # Add nodes
        if isinstance(nodes, dict):
            for node_id, attrs in nodes.items():
                if attrs is None:
                    attrs = {}
                elif not isinstance(attrs, dict):
                    raise TypeError(f"Node attributes for {node_id} must be a dict, got {type(attrs)}")
                g.add_node(node_id, **attrs)
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

            if u not in g:
                g.add_node(u)
            if v not in g:
                g.add_node(v)

            g.add_edge(u, v, key=k, **data)

        return cls(g, relationship)
      
    
    @classmethod
    def from_obo_ancestor_closure(cls, obo_path, seed_ids, relationship='is_a'):
        raw_graph = read_obo_without_gci_is_a(obo_path)
        rel_graph = cls.build_relationship_subgraph(raw_graph, relationship)
        alt_ids_to_id = OntologyGraph._build_id_map(raw_graph)
        
        keep = set()
        for term_id in seed_ids:
            tid = to_internal_id(term_id)
            if tid not in rel_graph:
                resolved = alt_ids_to_id.get(tid, None)
                if not resolved:
                    raise ValueError(f"Unknown term id: {term_id}")
                tid = resolved
            keep.add(tid)
            keep.update(nx.ancestors(rel_graph, tid))

        filtered_graph = raw_graph.subgraph(keep).copy()
        return cls(filtered_graph, relationship)

    
    @staticmethod
    def merge_ontologies(obo_paths: list[str], equivalence_fn):
        merged_raw = nx.MultiDiGraph()

        for path in obo_paths:
            raw_g = read_obo_without_gci_is_a(path)
            merged_raw.add_nodes_from(raw_g.nodes(data=True))
            merged_raw.add_edges_from(raw_g.edges(keys=True, data=True))

        uf = UnionFind()
        for node in merged_raw.nodes:
            uf.add(node)

        for node, data in merged_raw.nodes(data=True):
            for eq_id in equivalence_fn(node, data):
                if eq_id in merged_raw:
                    uf.union(node, eq_id)

        classes = defaultdict(set)
        for node in merged_raw.nodes:
            repr_n = uf.find(node)
            classes[repr_n].add(node)

        contracted = nx.MultiDiGraph()

        for repr_n, members in classes.items():
            contracted.add_node(repr_n, members=members)

        for u, v, k, data in merged_raw.edges(keys=True, data=True):
            repr_u = uf.find(u)
            repr_v = uf.find(v)
            if repr_u == repr_v:
                continue
            contracted.add_edge(repr_u, repr_v, key=k, **data)

        return contracted

    @staticmethod
    def build_relationship_subgraph(graph, relationship):
        non_obsolete_nodes = {
            node for node, data in graph.nodes(data=True)
            if data.get("is_obsolete") not in ("true", True)
        }
        
        rel_edges = [(u, v, k) for (u, v, k, data) in graph.edges(keys=True, data=True) 
                     if k == relationship and 
                     u in non_obsolete_nodes and 
                     v in non_obsolete_nodes and
                     not 'gci_filler' in data and
                     not 'gci_relation' in data]

        return graph.edge_subgraph(rel_edges).reverse(copy=True)
    
    def _find_roots(self, subgraph=None):
        g = self._rel_subgraph if subgraph is None else subgraph
        return {
            node for node in g.nodes
            if g.in_degree(node) == 0
        }

    def _compute_depths(self):
        depths = {}
        for node in nx.topological_sort(self._rel_subgraph):
            parents = list(self._rel_subgraph.predecessors(node))
            depths[node] = 0 if not parents else 1 + max(depths[p] for p in parents)
        return depths

    def ancestors(self, term_id) -> set:
        if term_id not in self._ancestor_cache:
            self._ancestor_cache[term_id] = (
                nx.ancestors(self._rel_subgraph, term_id)
                if term_id in self._rel_subgraph else set()
            )
        return self._ancestor_cache[term_id]
    
    def ancestor_closure(self, term_ids):
        keep = set()
        for t in term_ids:
            t = to_internal_id(t)
            if t not in self._rel_subgraph:
                logger.error('Can not compute ancestor closure for unknown id: %s', t)
                raise ValueError(f'Can not compute ancestor closure for unknown id: {t}')
            keep.add(t)
            keep.update(nx.ancestors(self._rel_subgraph, t))
        return keep
    
    def induced_subgraph(self, term_ids, as_ontology_graph=False):
        keep = self.ancestor_closure(term_ids)
        sub = self.graph.subgraph(keep).copy()
        if as_ontology_graph:
            return OntologyGraph(sub, self.relationship)
        return sub

    
    def _descendant_counts(self):
        return {
            node_id: len(nx.descendants(self._rel_subgraph, node_id))  +1
            for node_id in self._rel_subgraph.nodes
        }
    
    def find_lca(self, *term_ids):
        term_ids = [to_internal_id(t) for t in term_ids]
        common_ancestors = set.intersection(*[self.ancestors(t) | {t} for t in term_ids])
        if not common_ancestors:
            return None

        max_depth = max(self._depths[a] for a in common_ancestors)
        lcas = [a for a in common_ancestors if self._depths[a] == max_depth]

        if len(lcas) == 1:
            return to_external_id(lcas[0])

        return max(map(to_external_id, lcas), key=lambda a: (self.compute_ic(a), a))
     
    def compute_ic(self, term_id):
        cached_count = self._descendant_counts_cache.get(term_id, None)
        if cached_count:
            freq = cached_count / self._node_num
            return -math.log(freq)
        else:
            logger.error('No descendant count cache computed for, %s', term_id)
            raise ValueError(f'No descendant count cache computed for: {term_id, self.graph}')

    @staticmethod
    def _build_id_map(graph):
        alt_id_to_id = {}
        for node_id, data in graph.nodes(data=True):
            for alt in data.get("alt_id", []):
                alt_id_to_id[alt] = node_id
        return alt_id_to_id

    # Maps provided term_id to canonical id, if term_id is an alternative id in the ontology
    def resolve_id(self, term_id) -> str:
        internal_id = to_internal_id(term_id)
        if internal_id in self._rel_subgraph:
            return term_id
        internal_id = self._alt_id_to_id.get(internal_id, None)
        if internal_id:
            return to_external_id(internal_id)
        return None
    
class UnionFind:
    def __init__(self):
        self.parent = {}
        
    def add(self, elem):
        if elem not in self.parent:
            self.parent[elem] = elem
    
    def find(self, elem):
        parent = self.parent.get(elem, None)
        if not parent:
            raise ValueError(f'{elem} has no parent!')
        if elem == parent:
            return elem
        return self.find(parent)
    
    def union(self, elem_a, elem_b):
        repr_a = self.find(elem_a)
        repr_b = self.find(elem_b)
        self.parent[repr_b] = repr_a

_DOID_EXACTMATCH_PATTERN = re.compile(r"^skos:exactMatch\s+(DOID:[^\s]+)", re.IGNORECASE)     
def disease_equivalence_fn(mondo_id: str, mondo_data: dict):
    property_values = mondo_data.get('property_value', [])
    exact_matches = []
    for pv in property_values:
        pv = pv.strip()
        m = _DOID_EXACTMATCH_PATTERN.match(pv)
        if m:
            exact_matches.append(m.group(1))
    return exact_matches


