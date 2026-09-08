import sqlite3
from textmining.enums import HitType
from textmining.ontology import OntologyGraph
from textmining.db.loaders.entity import load_accession_to_id



def load_synonyms(con: sqlite3.Connection, ontology_graphs: dict[HitType, OntologyGraph]):
    accession_to_id = load_accession_to_id(con)
    for graph in ontology_graphs.values():
        entries = list(graph.extract_synonyms())
        rows = [
            {
                'synonym_name': syn,
                'synonym_type': 'STANDARD',
                'entity_id': accession_to_id[term_id],
            }
            for term_id, syns, _ in entries
            for syn in syns
        ]
        rows.extend([
            {
                'synonym_name': abbrev,
                'synonym_type': 'ABBREVIATION',
                'entity_id': accession_to_id[term_id],
            }
            for term_id, _, abbrevs in entries
            for abbrev in abbrevs
        ])

        con.executemany("""INSERT INTO synonym 
                    (synonym_name, synonym_type, entity_id) 
                    VALUES (:synonym_name, :synonym_type, :entity_id)""",
                    rows
                    )
