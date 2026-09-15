import sqlite3
from pathlib import Path
from typing import Iterator
from textmining.enums import HitType
from textmining.ontology import OntologyGraph
from textmining.models import Association
from textmining.db.loaders.entity import load_accession_to_id
from textmining.results_io import read_associations_tsv

def load_associations(con: sqlite3.Connection, associations_path: Path):
    associations = read_associations_tsv(associations_path)
    accession_to_id = load_accession_to_id(con)
    rows = (
        {
            'mirna_entity_id': accession_to_id[assoc.normalized_ids[0]],
            'term_entity_id': accession_to_id[assoc.normalized_ids[1]],
            'term_type': assoc.entity_types[1].value,
            'score': assoc.score,
        }
        for assoc in associations if accession_to_id.get(assoc.normalized_ids[0], None) #TODO: remove this. Currently this crashed due to dead mirnas
    )
    con.executemany("""INSERT INTO association 
                (mirna_entity_id, term_entity_id, term_type, score) 
                VALUES (:mirna_entity_id, :term_entity_id, :term_type, :score)""",
                rows
                )

def load_(con: sqlite3.Connection) -> dict[str, int]:
    rows = con.execute("SELECT accession, id FROM entity").fetchall()
    return {accession: id for accession, id in rows}
