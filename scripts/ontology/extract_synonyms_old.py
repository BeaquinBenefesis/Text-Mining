import networkx
import obonet
import argparse
import urllib.request
import os


def get_links(ontologies):
    out = []
    with open (ontologies, 'r') as o:
        for line in o:
            out.append(line.strip('\n'))
    return out

def get_exact_synonyms(node_data):
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

parser = argparse.ArgumentParser(
    description="""Parses an file containing obo links and generate a synonym file with the following format:
<id>:<syn1>|<syn2>|<syn3>|...
where the assigned ids are retrieved from the ontology.
"""
)

parser.add_argument(
    "-obo", metavar="obo", required=True, help="Path to file containing obo links"
)

parser.add_argument(
    "-out", metavar="out", required=True, help="Path to output dir."
)

args = parser.parse_args()

obo_links = get_links(args.obo)
opener = urllib.request.build_opener()
opener.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')]
urllib.request.install_opener(opener)
out = args.out

for link in obo_links:
    print(f"Fetching {link}")
    graph = obonet.read_obo(link)
    ontology_name = graph.graph.get('ontology', 'Unkown')


    with open(os.path.join(out, ontology_name), "w") as f:
        for node_id, data in graph.nodes(data=True):
            # Skip obsolete terms
            if not data or data.get("is_obsolete") == "true":
                continue

            name = data.get("name")

            # Skip entries without a name or id instead of crashing
            if not name or not node_id:
                print(f"Warning: skipping entry without name or id — id={node_id}, name={name}")
                continue

            syns = []

            # Add main name
            syns.append(name)

            # Add exact synonyms
            exact_syns = get_exact_synonyms(data)
            if exact_syns:
                syns.extend(exact_syns)

            # Remove potential duplicates
            syns = list(set(syns))

            if syns:
                id_parts = node_id.split(':')
                final_id = '_'.join(id_parts)
                f.write(f"{final_id}:{'|'.join(syns)}\n")
