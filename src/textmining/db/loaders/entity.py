import sqlite3
from textmining.config import MirbaseResources
from textmining.mirbase import load_mirbase
from textmining.enums import HitType
from textmining.ontology import OntologyGraph
from textmining.resources import ONTOLOGY_SOURCES
from textmining.ontology import to_external_id



def load_entities(con: sqlite3.Connection, mirbase: MirbaseResources, ontology_graphs: dict[HitType, OntologyGraph]):
    _, nodes, _ = load_mirbase(
        families_tsv=mirbase.families_path,
        precursors_tsv=mirbase.precursor_path,
        mature_tsv=mirbase.mature_path,
        parent_to_child_tsv=mirbase.parent_to_child_path,
    )
    con.executemany("""INSERT INTO entity 
                    (accession, primary_name, entity_type, source, obsolete, reference_level) 
                    VALUES (:accession, :primary_name, :entity_type, :source, :obsolete, :reference_level)""",
                    [{
                    'accession': node['accession'],
                    'primary_name': node['name'],
                    'entity_type': HitType.MIR.value,
                    'source': 'mirbase',
                    'obsolete': 0,
                    'reference_level': node['type']
                    } for node in nodes.values()]
                    )
    
    for entity_type, graph in ontology_graphs.items():
        con.executemany("""INSERT INTO entity 
                    (accession, primary_name, entity_type, source, obsolete, reference_level) 
                    VALUES (:accession, :primary_name, :entity_type, :source, :obsolete, :reference_level)""",
                    [{
                    'accession': to_external_id(node['id']),
                    'primary_name': node['name'],
                    'entity_type': entity_type.value,
                    'source': ONTOLOGY_SOURCES[entity_type].source,
                    'obsolete': 0,
                    'reference_level': None
                    } for node in graph.iter_nodes() if node.get('name')]
                    )

def load_accession_to_id(con: sqlite3.Connection) -> dict[str, int]:
    rows = con.execute("SELECT accession, id FROM entity").fetchall()
    return {accession: id for accession, id in rows}