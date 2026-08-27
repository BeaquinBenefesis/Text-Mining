"""
Analyze how many ambiguous-synonym DISEASE_id pairs are actually
parent/child (or ancestor/descendant) in the MONDO or DOID ontology.

Assumes you already have:
  - disease_mapping.json   (DISEASE_id -> source ontology ID(s))
  - your synonym file(s)   (used to (re)build the ambisyn dict)
  - compute_ambisyn_dict() / get_syn_line_terms() from your existing code
"""

import json
import itertools
from collections import defaultdict, Counter

import networkx as nx
import obonet

MONDO_OBO_PATH = "/mnt/raidbio2/extstud/studtemp/mitsopoulos/ontologies/diseases/mondo_disease_ontology.obo"
DOID_OBO_PATH = "/mnt/raidbio2/extstud/studtemp/mitsopoulos/ontologies/diseases/human_disease_ontology.obo"
MAPPING_PATH = "disease_mapping.json"
SYNONYM_PATHS = ["/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/disease.syn"]


def is_parent_child(graph, child_id, parent_id, transitive=True, relationship="is_a"):
    if child_id not in graph or parent_id not in graph:
        raise ValueError("Both child_id and parent_id must be present in the graph")
    if child_id == parent_id:
        return False

    if not transitive:
        if relationship is None:
            return graph.has_edge(child_id, parent_id)
        return graph.has_edge(child_id, parent_id, key=relationship)

    if relationship is None:
        sub = graph
    else:
        edges = [(u, v, k) for u, v, k in graph.edges(keys=True) if k == relationship]
        sub = graph.edge_subgraph(edges)

    if child_id not in sub or parent_id not in sub:
        return False
    return nx.has_path(sub, child_id, parent_id)


def related_either_direction(graph, id_a, id_b, transitive):
    """True if id_a is a parent/child of id_b in either direction."""
    if id_a not in graph or id_b not in graph:
        return False
    return (
        is_parent_child(graph, id_a, id_b, transitive=transitive)
        or is_parent_child(graph, id_b, id_a, transitive=transitive)
    )


def build_disease_to_ontology_ids(mapping: dict) -> dict:
    result = {}
    for disease_id, entry in mapping.items():
        ids = {"MONDO": None, "DOID": None}
        for eid in entry:
            if eid.startswith("MONDO:") and ids["MONDO"] is None:
                ids["MONDO"] = eid
            elif eid.startswith("DOID:") and ids["DOID"] is None:
                ids["DOID"] = eid
        result[disease_id] = ids
    return result



def classify_pair(disease_a, disease_b, id_map, mondo_graph, doid_graph):
    """
    Returns one of:
      'direct'      - direct parent/child edge in at least one ontology
      'transitive'  - related through ancestry, but not a direct edge
      'unrelated'   - both sides resolved to known terms, but no relationship
      'unresolved'  - could not check (missing/unknown ontology ID on one side)
    """
    ids_a = id_map.get(disease_a, {"MONDO": None, "DOID": None})
    ids_b = id_map.get(disease_b, {"MONDO": None, "DOID": None})

    checked_any = False
    found_transitive = False

    for onto, graph in (("MONDO", mondo_graph), ("DOID", doid_graph)):
        id_a, id_b = ids_a.get(onto), ids_b.get(onto)
        if not id_a or not id_b:
            continue
        if id_a not in graph or id_b not in graph:
            continue

        checked_any = True

        if related_either_direction(graph, id_a, id_b, transitive=False):
            return "direct"
        if related_either_direction(graph, id_a, id_b, transitive=True):
            found_transitive = True

    if found_transitive:
        return "transitive"
    if checked_any:
        return "unrelated"
    return "unresolved"



def analyze_ambisyn(ambisyn: dict, id_map: dict, mondo_graph, doid_graph, max_examples=10):
    results = Counter()
    examples = defaultdict(list)

    for term, disease_ids in ambisyn.items():
        for disease_a, disease_b in itertools.combinations(sorted(disease_ids), 2):
            label = classify_pair(disease_a, disease_b, id_map, mondo_graph, doid_graph)
            results[label] += 1
            if len(examples[label]) < max_examples:
                examples[label].append((term, disease_a, disease_b))

    return results, examples


def print_report(results, examples):
    total = sum(results.values())
    print(f"\nTotal ambiguous pairs analyzed: {total}")
    for label in ("direct", "transitive", "unrelated", "unresolved"):
        count = results.get(label, 0)
        pct = 100 * count / total if total else 0
        print(f"  {label:12s}: {count:5d} ({pct:5.1f}%)")

    print("\nExample pairs per category:")
    for label, exs in examples.items():
        print(f"\n[{label}]")
        for term, a, b in exs:
            print(f"  '{term}': {a} <-> {b}")


def main():
    print("Loading ontologies...")
    mondo_graph = obonet.read_obo(MONDO_OBO_PATH)
    doid_graph = obonet.read_obo(DOID_OBO_PATH)

    print("Loading mapping...")
    with open(MAPPING_PATH, encoding="utf-8") as f:
        mapping = json.load(f)
    id_map = build_disease_to_ontology_ids(mapping)

    print("Computing ambiguous synonyms...")

    from SynFileUtils import compute_ambisyn_dict
    ambisyn = compute_ambisyn_dict(SYNONYM_PATHS)

    print("Classifying ambiguous pairs...")
    results, examples = analyze_ambisyn(ambisyn, id_map, mondo_graph, doid_graph)

    print_report(results, examples)


if __name__ == "__main__":
    main()