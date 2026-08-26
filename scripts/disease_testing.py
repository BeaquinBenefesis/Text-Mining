import obonet
import networkx as nx
import re
from collections import defaultdict
import json
from textmining.paths import OUTPUTS_DIR

MONDO_OBO_PATH = "/mnt/raidbio2/extstud/studtemp/mitsopoulos/ontologies/diseases/mondo_disease_ontology.obo"
DOID_OBO_PATH = '/mnt/raidbio2/extstud/studtemp/mitsopoulos/ontologies/diseases/human_disease_ontology.obo'

MONDO_DISEASE_ROOT_IDS = ['MONDO:0020683', 'MONDO:7770006', 'MONDO:7770007', 'MONDO:7770008']
DOID_DISEASE_ROOT_IDS = ['DOID:0050117', 'DOID:7', 'DOID:14566', 'DOID:150', 'DOID:0014667', 'DOID:630', 'DOID:0080015', 'DOID:225']

# Output paths
OUTPUT_MAPPING = str(OUTPUTS_DIR / 'disease_mapping.json')
OUTPUT_SYNONYMS = str(OUTPUTS_DIR / 'disease.syn')
OUTPUT_ABBREVIATIONS = str(OUTPUTS_DIR / 'disease_abbreviation.syn')

MESH_EXACTMATCH_PATTERN = re.compile(r"^skos:exactMatch\s+(MESH:[^\s]+)", re.IGNORECASE)
DOID_EXACTMATCH_PATTERN = re.compile(r"^skos:exactMatch\s+(DOID:[^\s]+)", re.IGNORECASE)
OMIM_EXACTMATCH_PATTERN = re.compile(r"^skos:exactMatch\s+(OMIM:[^\s]+)", re.IGNORECASE)
EXACTMATCH_PATTERN = re.compile(r"^skos:exactMatch\s+(\S+:[^\s]+)", re.IGNORECASE)

OBO_SYNONYM_RE = re.compile(
    r'^\s*"((?:[^"\\]|\\.)*)"\s+(EXACT|RELATED|BROAD|NARROW)(?:\s+([^\s\[]+))?'
)

ABBREVIATION_TAGS = {"ABBREVIATION", "OMO:0003012", "OMO:0003000"}


def is_obsolete(node_data: dict) -> bool:
    value = node_data.get("is_obsolete", "")
    if isinstance(value, list):
        return any(str(v).lower() == "true" for v in value)
    return str(value).lower() == "true"


def get_property_values(node_data: dict) -> list[str]:
    property_values = node_data.get("property_value", [])
    if isinstance(property_values, str):
        return [property_values]
    return property_values


def get_exactmatch_property_values(node_data: dict) -> list[str]:
    out = []
    for prop in get_property_values(node_data):
        prop = prop.strip()
        m = EXACTMATCH_PATTERN.match(prop)
        if m:
            out.append(m.group(1))
    return out


def descendants_exclusive(graph: nx.MultiDiGraph, root_ids: list[str]) -> set[str]:
    reversed_graph = graph.reverse(copy=False)
    desc = set()
    for root_id in root_ids:
        desc.update(nx.descendants(reversed_graph, root_id))
    return desc


def get_synonyms(node_data: dict) -> dict:
    result = {
        "exact": [],
        "abbreviation": []
    }
    name = node_data.get('name', None)
    if not name:
        raise ValueError(f'Disease with no name found: {node_data}')
    
    result['exact'].append(name)
    
    for s in node_data.get("synonym", []):
        match = OBO_SYNONYM_RE.match(s)
        if not match:
            continue
            
        text, scope, syn_type = match.groups()
        
        if scope == "EXACT":
            clean_text = text.replace(r'\"', '"')
                    
            if syn_type in ABBREVIATION_TAGS:
                result["abbreviation"].append(clean_text)
            else:
                result["exact"].append(clean_text)
                
    return result


def main():    
    print("Loading MONDO graph...")
    mondo_graph = obonet.read_obo(MONDO_OBO_PATH)
    mondo_disease_terms = descendants_exclusive(mondo_graph, MONDO_DISEASE_ROOT_IDS)
    
    print("Loading DOID graph...")
    doid_graph = obonet.read_obo(DOID_OBO_PATH)
    doid_disease_terms = descendants_exclusive(doid_graph, DOID_DISEASE_ROOT_IDS)
    
    mapping = {}
    seen_doid_to_ids = {}
    global_synonyms = defaultdict(set)
    global_abbreviations = defaultdict(set)
    
    # 1. Process MONDO terms
    for term_id in mondo_disease_terms:
        data = mondo_graph.nodes[term_id]

        if not data or is_obsolete(data):
            continue
        
        extracted_syns = get_synonyms(data)
        
        global_synonyms[term_id].update(extracted_syns['exact'])
        if extracted_syns['abbreviation']:
            global_abbreviations[term_id].update(extracted_syns['abbreviation'])
        
        exact_id_matches = get_exactmatch_property_values(data)
        exact_id_matches.append(term_id)
        mapping[term_id] = exact_id_matches
        
        eq_doids = [id for id in exact_id_matches if id.startswith('DOID')]
        if eq_doids and len(eq_doids) > 0:
            for eq_doid in eq_doids:
                seen_doid_to_ids[eq_doid] = term_id
            

    # 2. Process DOID terms
    for term_id in doid_disease_terms:
        data = doid_graph.nodes[term_id]
        
        if is_obsolete(data):
            continue
        
        extracted_syns = get_synonyms(data)
        found_synonyms = set(extracted_syns['exact'])
        found_abbreviations = set(extracted_syns['abbreviation'])
        
        if term_id in seen_doid_to_ids:
            stored_id = seen_doid_to_ids[term_id]
            stored_synonyms = global_synonyms[stored_id]
            stored_abbreviations = global_abbreviations[stored_id]
            
            if found_synonyms - stored_synonyms:
                #print(f'Expanding synonyms: {stored_synonyms} with {found_synonyms - stored_synonyms}')
                stored_synonyms.update(found_synonyms)
            if found_abbreviations - stored_abbreviations:
                #print(f'Expanding abbreviations: {stored_abbreviations} with {found_abbreviations - stored_abbreviations}')
                stored_abbreviations.update(found_abbreviations)
            continue
        
        # New DOID disease term not matched via MONDO
        #global_synonyms[term_id].update(found_synonyms)
        #if found_abbreviations:
        #    global_abbreviations[term_id].update(found_abbreviations)
            
        #mapping[term_id] = {'DOID': term_id}

    formatted_mapping = {
        dis_id.replace(':', '_'): [m.replace(':', '_') for m in maps] 
        for dis_id, maps in mapping.items()
    }
    with open(OUTPUT_MAPPING, "w", encoding="utf-8") as f:
        json.dump(formatted_mapping, f, indent=2)

    # 4. Dump Synonyms
    print(f"Writing synonyms to {OUTPUT_SYNONYMS}...")
    with open(OUTPUT_SYNONYMS, "w", encoding="utf-8") as f:
        for dis_id in sorted(global_synonyms.keys(), key=lambda x: int(x.split(':')[1])):
            syns = sorted(list(global_synonyms[dis_id]))
            formatted_syns = "|".join(syns)
            formatted_id = dis_id.replace(':', '_')
            f.write(f"{formatted_id}:{formatted_syns}\n")

    # 5. Dump Abbreviations
    print(f"Writing abbreviations to {OUTPUT_ABBREVIATIONS}...")
    with open(OUTPUT_ABBREVIATIONS, "w", encoding="utf-8") as f:
        for dis_id in sorted(global_abbreviations.keys(), key=lambda x: int(x.split(':')[1])):
            abbrs_raw = sorted(list(global_abbreviations[dis_id]))
            abbrs = [f'{a}@EXACT' for a in abbrs_raw]
            formatted_id = dis_id.replace(':', '_')
            if len(abbrs) > 0:
                formatted_abbrs = "|".join(abbrs)
                f.write(f"{formatted_id}:{formatted_abbrs}\n")

    print("Done!")

if __name__ == "__main__":
    main()