"""Search index: one row per surface form a user might type.

Restricted to entities that are actually reachable. This is what keeps the
2,854,488 TAXON entities -- which are disambiguation context for miRNA
normalisation, never association targets -- out of the search path, along with
the ~60k ontology terms that never received a hit.

Ancestors from `ontology_closure` are included even when they carry no direct
association of their own: searching a broad term like 'cancer' and reaching the
associations of its subtypes is the entity-centric view's whole purpose, and a
broad term frequently has no association in its own right.
"""
import logging
import sqlite3

logger = logging.getLogger(__name__)


def load_search_names(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TEMP TABLE reachable AS
            SELECT DISTINCT term_entity_id  AS id FROM association
            UNION SELECT DISTINCT mirna_entity_id FROM association
            UNION SELECT DISTINCT ancestor_id     FROM ontology_closure
            UNION SELECT e.id FROM entity e
                  JOIN mir_mention_article m ON m.mir_key = e.accession
    """)
    n_reachable = con.execute("SELECT count(*) FROM reachable").fetchone()[0]

    con.execute("""
        INSERT INTO search_name (name_lower, display_name, entity_id, kind)
        SELECT lower(e.primary_name), e.primary_name, e.id, 'primary'
        FROM entity e JOIN reachable r ON r.id = e.id
    """)

    con.execute("""
        INSERT INTO search_name (name_lower, display_name, entity_id, kind)
        SELECT lower(s.synonym_name), s.synonym_name, s.entity_id,
               CASE WHEN s.synonym_type = 'LEGACY' THEN 'legacy' ELSE 'synonym' END
        FROM synonym s JOIN reachable r ON r.id = s.entity_id
    """)

    # Accessions are identifiers, not names, but users paste them.
    con.execute("""
        INSERT INTO search_name (name_lower, display_name, entity_id, kind)
        SELECT lower(e.accession), e.accession, e.id, 'primary'
        FROM entity e JOIN reachable r ON r.id = e.id
    """)

    # Ambiguous miRBase identifiers resolve to no single entity on purpose --
    # entity_id stays NULL and the UI routes them to the disambiguation view.
    con.execute("""
        INSERT INTO search_name (name_lower, display_name, entity_id, kind)
        SELECT name_lower, min(display_name), NULL, 'conflict' FROM (
            SELECT lower(mirna_name) AS name_lower, min(mirna_name) AS display_name
            FROM mirna_name_history
            -- grouped within reference_level: miRBase separates a precursor from
            -- its mature product by capitalisation alone, so a case-insensitive
            -- group across both levels reports every hairpin/mature pair as a
            -- conflict (24,768 instead of 274)
            GROUP BY reference_level, lower(mirna_name)
            HAVING count(DISTINCT accession) > 1
        ) GROUP BY name_lower
    """)

    con.execute("""
        DELETE FROM search_name WHERE rowid NOT IN (
            SELECT min(rowid) FROM search_name
            GROUP BY name_lower, ifnull(entity_id, -1), kind
        )
    """)
    con.execute("DROP TABLE reachable")

    counts = dict(con.execute("SELECT kind, count(*) FROM search_name GROUP BY kind"))
    logger.info("Loaded search_name over %d reachable entity(ies): %s", n_reachable, counts)
