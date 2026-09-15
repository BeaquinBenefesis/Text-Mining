import logging
import sqlite3
from textmining.enums import HitType
from textmining.ontology import OntologyGraph
from textmining.db.loaders.entity import load_accession_to_id
from textmining.db.loaders.mirna_history import conflicted_names
from textmining.resources import EXTRACTABLE_SYNONYMS

logger = logging.getLogger(__name__)


def load_synonyms(con: sqlite3.Connection, ontology_graphs: dict[HitType, OntologyGraph]):
    accession_to_id = load_accession_to_id(con)
    ontology_roots = {
        entity_type: [r for spec in specs for r in spec.roots]
        for entity_type, specs in EXTRACTABLE_SYNONYMS.items()
    }
    for entity_type, graph in ontology_graphs.items():
        entries = list(graph.extract_synonyms(ontology_roots.get(entity_type, None)))
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


def load_mirna_legacy_synonyms(con: sqlite3.Connection, history_rows: list[dict]) -> None:
    """Historical miRBase names as literal surface forms.

    This is the miRNA synonym source the implementation plan records as missing:
    `mir_regex.syn` holds regex patterns, not surface forms, so miRNA synonyms
    were skipped entirely. 8,421 of 49,440 mature and 1,329 of 39,314 precursor
    accessions have carried more than one name, so a reader searching a legacy
    name ('hsa-miR-34b*') would otherwise find nothing.

    Names carried by more than one accession are deliberately excluded. Inserting
    those as plain synonyms would silently resolve an ambiguous identifier to one
    arbitrary accession, which is exactly the failure the disambiguation view
    exists to prevent; they reach the UI through `search_name` instead.
    """
    accession_to_id = load_accession_to_id(con)
    ambiguous = conflicted_names(history_rows)
    primary_names = {
        entity_id: name
        for entity_id, name in con.execute(
            "SELECT id, primary_name FROM entity WHERE entity_type = 'MIR'"
        )
    }

    seen: set[tuple[int, str]] = set()
    rows = []
    for row in history_rows:
        name = row["mirna_name"]
        if name.lower() in ambiguous:
            continue
        entity_id = accession_to_id.get(row["accession"])
        if entity_id is None:
            continue
        if primary_names.get(entity_id) == name:
            continue  # already reachable as the entity's primary name
        key = (entity_id, name)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"synonym_name": name, "synonym_type": "LEGACY", "entity_id": entity_id})

    con.executemany(
        """INSERT INTO synonym (synonym_name, synonym_type, entity_id)
           VALUES (:synonym_name, :synonym_type, :entity_id)""",
        rows,
    )
    logger.info(
        "Loaded %d legacy miRNA synonym(s); %d ambiguous name(s) withheld for disambiguation",
        len(rows), len(ambiguous),
    )
