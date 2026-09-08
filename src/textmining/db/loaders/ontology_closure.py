import sqlite3
from textmining.enums import HitType
from textmining.ontology import OntologyGraph, to_internal_id
from textmining.db.loaders.entity import load_accession_to_id


def load_ontology_closure(con: sqlite3.Connection, ontology_graphs: dict[HitType, OntologyGraph]):
    accession_to_id = load_accession_to_id(con)
    id_to_accession = {entity_id: accession for accession, entity_id in accession_to_id.items()}

    for entity_type, graph in ontology_graphs.items():
        observed_ids = {
            row[0] for row in con.execute(
                "SELECT DISTINCT term_entity_id FROM association WHERE term_type = ?",
                (entity_type.value,),
            )
        }

        pairs = set()
        for descendant_id in observed_ids:
            descendant_idx = graph.map_to_index(to_internal_id(id_to_accession[descendant_id]))
            for ancestor_idx in graph.ancestors(descendant_idx):
                ancestor_accession = graph.map_idx_to_external_id(ancestor_idx)
                ancestor_id = accession_to_id.get(ancestor_accession)
                if ancestor_id is None:
                    continue
                pairs.add((ancestor_id, descendant_id))

        con.executemany(
            """INSERT INTO ontology_closure (ancestor_id, descendant_id)
               VALUES (:ancestor_id, :descendant_id)""",
            [{'ancestor_id': a, 'descendant_id': d} for a, d in pairs],
        )
