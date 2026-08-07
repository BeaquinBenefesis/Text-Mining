import obonet
import networkx as nx
import math
from collections import defaultdict
import re
import tempfile
from pathlib import Path
import datetime

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
        print(f'Reading complete {datetime.datetime.now()}')
        self.relationship = relationship
        self._rel_subgraph = self._build_relationship_subgraph()
        print(f'Filtering complete {datetime.datetime.now()}')
        if not nx.is_directed_acyclic_graph(self._rel_subgraph):
            raise nx.NetworkXError("LCA only defined on directed acyclic graphs.")
        if len(self._rel_subgraph) == 0:
            raise nx.NetworkXPointlessConcept("LCA meaningless on null graphs.")
        self.roots = self._find_roots()
        self._ancestor_cache = {}
        self._depths = self._compute_depths()
        print(f'Depths computed {datetime.datetime.now()}')
        self._descendant_counts_cache = self._descendant_counts()
        print(f'Ancestor counts computed {datetime.datetime.now()}')
        self._node_num = self._rel_subgraph.number_of_nodes()
    
    @classmethod
    def from_obo(cls, obo_path, relationship='is_a'):
        return cls(read_obo_without_gci_is_a(obo_path), relationship)
    
    @classmethod
    def from_merge(cls, obo_paths, equivalence_fn, relationship='is_a'):
        return cls(cls.merge_ontologies(obo_paths, equivalence_fn), relationship)
    
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

        
    
    def _build_relationship_subgraph(self):
        non_obsolete_nodes = {
            node for node, data in self.graph.nodes(data=True)
            if data.get("is_obsolete") not in ("true", True)
        }
        
        rel_edges = [(u, v, k) for (u, v, k, data) in self.graph.edges(keys=True, data=True) 
                     if k == self.relationship and 
                     u in non_obsolete_nodes and 
                     v in non_obsolete_nodes and
                     not 'gci_filler' in data and
                     not 'gci_relation' in data]

        return self.graph.edge_subgraph(rel_edges).reverse(copy=True)
    
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

        return max(to_external_id(lcas), key=lambda a: (self.compute_ic(a), a))
        
    def compute_ic(self, term_id):
        cached_count = self._descendant_counts_cache.get(term_id, None)
        if cached_count:
            freq = cached_count / self._node_num
            return -math.log(freq)
        else:
            raise ValueError(f'Can not compute information content for unknown id: {term_id, self.graph}')

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

print(datetime.datetime.now())
tax_onto = OntologyGraph.from_obo('/mnt/raidbio2/extstud/studtemp/mitsopoulos/ontologies/taxonomy/ncbi_taxonomy.obo')
print(tax_onto.find_lca('NCBITaxon_915388', 'NCBITaxon_995317'))
print(datetime.datetime.now())


