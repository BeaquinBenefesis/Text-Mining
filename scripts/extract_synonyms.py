import argparse
from pathlib import Path
from textmining.ontology import OntologyGraph
from textmining.synonym_utils import write_syn_file

parser = argparse.ArgumentParser(
    description=
"""Parses a .obo file and generate a synonym file with the following format:
<id>:<syn1>|<syn2>|<syn3>|...
where the assigned ids are retrieved from the ontology. Root ids can be specified with the optional --roots paramter.
"""
)

parser.add_argument(
    "-obo", 
    metavar="obo", 
    required=True, 
    help="Path to obo file or url"
)

parser.add_argument(
    "-out", 
    metavar="out",
    required=True, 
    help="Path to output file."
)

parser.add_argument(
    '--roots',
    metavar='roots',
    nargs='+',        
    default=None,
    help='List of root IDs'
)

parser.add_argument(
    '--relationship',
    type=str,
    default='is_a',
    help='Type of relationship (default: is_a)'
)

parser.add_argument(
    '--exclude-gci',
    action='store_true',
    default=False,
    help='Exclude GCI lines (default: False)'
)

parser.add_argument(
    '--no-ignore-obsolete',
    action='store_true',
    default=False,
    help='Do not ignore obsolete items (default: False)'
)

if __name__ == '__main__':
    args = parser.parse_args()
    obo = args.obo
    out_path = Path(args.out)
    roots = args.roots
    rel = args.relationship
    exclude_gci = args.exclude_gci
    ignore_obsolete = not args.no_ignore_obsolete
    
    graph = None
    if obo.startswith(("http://", "https://", "ftp://")): 
        graph = OntologyGraph.from_url(url=obo,
                                       relationship=rel,
                                       exclude_gci=exclude_gci,
                                       ignore_obsolete=ignore_obsolete)
    else:
        graph = OntologyGraph.from_obo(obo_path=obo,
                            relatioship=rel,
                            exclude_gci=exclude_gci,
                            ignore_obsolete=ignore_obsolete)
    write_syn_file(
        output=out_path,
        synonym_groups=graph.extract_synonyms(roots)
    )