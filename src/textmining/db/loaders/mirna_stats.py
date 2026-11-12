"""Article count of every mentioned miRNA and its rank among comparable miRNAs.

Precomputed because the rank needs the count of the whole population.
"""
import logging
import sqlite3

logger = logging.getLogger(__name__)


def load_mirna_stats(con: sqlite3.Connection) -> None:
    """Must reproduce web.queries.mirna_stats exactly: n_articles is the number of
    articles mentioning the miRNA, breadth the number of associated terms.

    A miRNA is ranked by n_articles among those of its reference level and organism
    that are mentioned at least once. Families carry no organism and form one population.
    """
    con.execute("""
        INSERT INTO mirna_stats (entity_id, n_articles, breadth, pop_rank, pop_size)
        WITH mentioned AS (
            SELECT mir_key, count(*) AS n_articles
            FROM mir_mention_article GROUP BY mir_key
        ),
        breadth AS (
            SELECT mirna_entity_id, count(DISTINCT term_entity_id) AS n
            FROM association GROUP BY mirna_entity_id
        )
        SELECT e.id, m.n_articles, coalesce(b.n, 0),
               rank() OVER (PARTITION BY e.reference_level, e.organism ORDER BY m.n_articles DESC),
               count(*) OVER (PARTITION BY e.reference_level, e.organism)
        FROM entity e
        JOIN mentioned m ON m.mir_key = e.accession
        LEFT JOIN breadth b ON b.mirna_entity_id = e.id
        WHERE e.entity_type = 'MIR'
    """)
    n, populations = con.execute(
        "SELECT count(*), count(DISTINCT e.reference_level || '/' || ifnull(e.organism, '')) "
        "FROM mirna_stats s JOIN entity e ON e.id = s.entity_id"
    ).fetchone()
    logger.info("Ranked %d mentioned miRNA(s) in %d (level, organism) population(s)", n, populations)
