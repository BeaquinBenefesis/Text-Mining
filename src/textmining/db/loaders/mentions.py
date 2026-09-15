"""Mention layer: every miRNA mention in the corpus, not only those that produced
an association.
"""
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

_INSERT_BATCH = 500_000

def _blacklist_key_sql() -> str:
    """SQL rebuilding the name MirNormalizer tested against its blacklist.

    Blacklisted hits carry no normalized_id, so they can only be keyed on their
    name -- and it has to be the *same* name the normalizer built, or the
    disambiguation view cannot join a timeline to `mirna_name_history`. That name
    is `_join_parts(prefix, body + suffix)` where the body comes from
    `MirIdMapper.resolve_token(entity_id)`, not from raw_text: the regex matches
    'miRNA' and 'microRNA' as readily as 'miR', so raw_text yields keys like
    'bmo-mirna-965' where the canonical name is 'bmo-mir-965'.
    """
    from textmining.normalization import MirIdMapper

    cases = " ".join(
        f"WHEN entity_id = '{entity_id}' THEN '{token}'"
        for entity_id, token in MirIdMapper.known_tokens().items()
    )
    body = f"CASE {cases} END"
    # _join_parts drops empty parts, so an absent prefix must not leave a '-'.
    return (
        "lower(CASE WHEN coalesce(prefix,'') = '' THEN '' ELSE prefix || '-' END"
        f" || {body} || coalesce(suffix,''))"
    )


_MENTION_SQL = """
SELECT
  CASE WHEN norm_status IN ('NORMALIZED','FALLBACK') THEN normalized_id
       WHEN norm_status = 'IN_BLACKLIST'             THEN {blacklist_key}
  END                                   AS mir_key,
  split_part(sentence_id, '.', 1)       AS external_id,
  norm_status = 'IN_BLACKLIST'          AS blacklisted
FROM read_csv(?, delim='\t', header=true, quote='', escape='',
              ignore_errors=true, sample_size=-1)
WHERE entity_type = 'MIR'
  AND norm_status IN ('NORMALIZED','FALLBACK','IN_BLACKLIST')
"""


def load_mentions(
    con: sqlite3.Connection,
    norm_path: Path,
    threads: int = 8,
    memory_limit: str = "24GB",
) -> None:
    """Populates `mir_mention_article`, inserting any article the corpus loader
    never saw. Must run after `corpus` (so existing articles keep their ids) and
    before `article_metadata` (so the articles added here also get backfilled).

    The memory limit is explicit because this runs mid-build, alongside the
    ontology graphs and the article reader's mmap indexes; duckdb's default is a
    share of total RAM and does not know about them.
    """
    import duckdb

    duck = duckdb.connect()
    duck.execute(f"PRAGMA threads={threads}")
    duck.execute(f"PRAGMA memory_limit='{memory_limit}'")

    logger.info("Scanning %s for miRNA mentions", norm_path)
    duck.execute(
        f"""CREATE TABLE mention AS
            SELECT mir_key, external_id, bool_or(blacklisted) AS blacklisted
            FROM ({_MENTION_SQL.format(blacklist_key=_blacklist_key_sql())}) WHERE mir_key IS NOT NULL
            GROUP BY mir_key, external_id""",
        [str(norm_path)],
    )
    n_pairs, n_keys, n_articles = duck.execute(
        "SELECT count(*), count(DISTINCT mir_key), count(DISTINCT external_id) FROM mention"
    ).fetchone()
    logger.info(
        "Found %d (miRNA, article) pair(s) over %d key(s) and %d article(s)",
        n_pairs, n_keys, n_articles,
    )

    article_ids = _insert_missing_articles(con, duck)

    inserted = 0
    cursor = duck.execute("SELECT mir_key, external_id, blacklisted FROM mention")
    while batch := cursor.fetchmany(_INSERT_BATCH):
        con.executemany(
            """INSERT OR IGNORE INTO mir_mention_article (mir_key, article_id, blacklisted)
               VALUES (?, ?, ?)""",
            [(mir_key, article_ids[external_id], int(blacklisted))
             for mir_key, external_id, blacklisted in batch],
        )
        inserted += len(batch)
        logger.info("  inserted %d/%d mention pair(s)", inserted, n_pairs)
    duck.close()


def _insert_missing_articles(con: sqlite3.Connection, duck) -> dict[str, int]:
    """The corpus loader only created articles that produced a co-occurrence.
    Mentions span more articles than that, and one with no year cannot be placed
    on a timeline, so the missing ones are inserted here to be backfilled by
    `article_metadata` in the next stage."""
    article_ids = {
        external_id: article_id
        for article_id, external_id in con.execute("SELECT id, external_id FROM article")
    }
    missing = [
        (external_id,)
        for (external_id,) in duck.execute("SELECT DISTINCT external_id FROM mention").fetchall()
        if external_id not in article_ids
    ]
    con.executemany("INSERT INTO article (external_id) VALUES (?)", missing)
    logger.info("Inserted %d article(s) that have mentions but no association", len(missing))

    article_ids.update({
        external_id: article_id
        for article_id, external_id in con.execute("SELECT id, external_id FROM article")
    })
    return article_ids


def load_corpus_year(con: sqlite3.Connection) -> None:
    """Per-year article totals -- the denominator for share normalisation.

    The corpus is 99% post-2010 and 46% post-2020, so raw per-year mention counts
    describe corpus coverage far more than research activity. Every timeline the
    UI renders divides by this.
    """
    con.execute(
        """INSERT INTO corpus_year (year, n_articles)
           SELECT year, count(*) FROM article WHERE year IS NOT NULL GROUP BY year"""
    )
    n = con.execute("SELECT count(*), sum(n_articles) FROM corpus_year").fetchone()
    logger.info("Loaded corpus_year: %d year(s), %s article(s) with a year", n[0], n[1])
