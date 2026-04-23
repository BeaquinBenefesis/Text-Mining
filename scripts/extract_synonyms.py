import networkx
import obonet
import argparse

def get_exact_synonyms(node_data):
    exact_syns = []
    
    for s in node_data.get("synonym", []):
        parts = s.split('"')
        
        if len(parts) > 2:
            text = parts[1]
            scope = parts[2].strip().split()[0]  # EXACT / RELATED / BROAD / NARROW
            
            if scope == "EXACT":
                exact_syns.append(text)
    
    return exact_syns

parser = argparse.ArgumentParser(
    description="""Parses an .obo file and generate a synonym file with the following format:
<id>:<syn1>|<syn2>|<syn3>|...
where the assigned ids are retrieved from the ontology.
"""
)

parser.add_argument(
    "-obo", metavar="obo", required=True, help="Path to .obo input file"
)

parser.add_argument(
    "-syn", metavar="syn", required=True, help="Path to .syn output file."
)

args = parser.parse_args()

obo = args.obo
syn = args.syn

graph = obonet.read_obo(obo)

with open(syn, "w") as f:
    for node_id, data in graph.nodes(data=True):
        syns = []
        name = data.get("name")

        if not name or not node_id:
            raise RuntimeError("Found entry without a name or id")

        # Add main name
        if name:
            syns.append(name)
        
        # Add exact synonyms
        # TODO: Maybe use broad?
        exact_syns = get_exact_synonyms(data)
        if exact_syns:
            syns.extend(exact_syns)

        # Remove potential duplicates
        syns = list(set(syns))

        if syns:
            f.write(f"{node_id}:{'|'.join(syns)}\n")
