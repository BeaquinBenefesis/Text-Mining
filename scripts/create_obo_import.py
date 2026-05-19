import networkx
import obonet
import argparse
import os
import re
import urllib.request
import csv


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

def get_links(ontologies):
    out = []
    with open (ontologies, 'r') as o:
        for line in o:
            out.append(line.strip('\n'))
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Parses an .obo file and generate a .csv file for neo4j import"
    )

    parser.add_argument(
        "-obo", metavar="obo", required=True, help="Path to file containing .obo"
    )

    parser.add_argument(
        "-out", metavar="out", required=True, help="Path to output directory."
    )

    parser.add_argument('-header', required=False, action='store_true', help='Save headers to separate files.')

    args = parser.parse_args()
    obo_links = get_links(args.obo)
    out = args.out
    head =args.header

    opener = urllib.request.build_opener()
    opener.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')]
    urllib.request.install_opener(opener)
    
    node_header = 'termId:ID,name,source,definition,synonyms:string[],:LABEL\n'
    edge_header = ':START_ID,:END_ID,:TYPE\n'

    if (args.header):
        with open(os.path.join(out, 'node_header.csv'), 'w') as nh, \
        open (os.path.join(out, 'edge_header.csv'), 'w') as eh:
            nh.write(node_header)
            eh.write(edge_header)


    for link in obo_links:
        print(f'Fetching {link}...')
        graph = obonet.read_obo(link)
        ontology_name = graph.graph.get('ontology', 'Unkown')

        with open(os.path.join(out, f'{ontology_name}_nodes.csv'), 'w') as nodes, \
            open(os.path.join(out, f'{ontology_name}_edges.csv'), 'w') as edges:
            
            node_writer = csv.writer(nodes, quoting=csv.QUOTE_ALL)
            edge_writer = csv.writer(edges, quoting=csv.QUOTE_ALL)



            if not args.header:
                nodes.write(node_header)
                edges.write(edge_header)

            for node_id, data in graph.nodes(data=True):

                if not node_id:
                    raise RuntimeError("Encountered entry with no id!")

                name = data.get('name', 'Not available')
                synonyms = get_exact_synonyms(data)

                raw_definition = data.get('def', 'No definition available')
                clean_definition = "No definition available"
                citations = []
                if 'def' in data:
                    # Match anything inside the first set of quotation marks
                    text_match = re.search(r'"([^"]*)"', raw_definition)
                    if text_match:
                        clean_definition = text_match.group(1)
                                
                node_writer.writerow([node_id,name,ontology_name,clean_definition,";".join(synonyms),'TERM'])
                edge_writer.writerows([[node_id,parent_id,'IS_A'] for parent_id in graph.successors(node_id)])
                
