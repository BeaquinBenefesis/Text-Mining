"""Downloadable files written at build time: the normalized hits of one run per
entity type, and the associations of the built database with their dominant label.

No sentence texts are exported (file size, text licensing).
"""
import argparse
import csv
import gzip
import logging
import shutil
import sqlite3
from pathlib import Path

from textmining.db.connect import DB_PATH, open_readonly
from textmining.logging_utils import setup_logging
from textmining.paths import OUTPUTS_DIR

logger = logging.getLogger(__name__)

NORMALIZED_STATUSES = ('NORMALIZED', 'FALLBACK', 'ARM_FALLBACK')

# Taxon hits are skipped as in the database: no association references them.
# A miRNA hit covers only its stem ("miR"), so matched_text is not the full name.
_HITS_SQL = f"""
SELECT
  entity_type,
  split_part(sentence_id, '.', 1)                     AS article_id,
  sentence_id,
  start_position                                      AS "start",
  hit_length                                          AS "length",
  raw_text                                            AS matched_text,
  normalized_id,
  CASE WHEN entity_type = 'MIR' THEN norm_status END  AS status
FROM read_csv(?, delim='\t', header=true, quote='', escape='',
              ignore_errors=true, sample_size=-1, all_varchar=true)
WHERE norm_status IN {NORMALIZED_STATUSES}
  AND entity_type <> 'TAXON'
"""

_ASSOCIATIONS_SQL = """
SELECT m.accession, m.primary_name, m.reference_level, m.organism,
       t.accession, t.primary_name, a.term_type, t.organism,
       a.score, a.n_articles, a.n_direct_articles, a.dominant_label, a.dominant_label_articles
FROM association a
JOIN entity m ON m.id = a.mirna_entity_id
JOIN entity t ON t.id = a.term_entity_id
ORDER BY a.id
"""
_ASSOCIATION_COLUMNS = (
    "mirna_accession", "mirna_name", "mirna_level", "mirna_organism",
    "term_accession", "term_name", "term_type", "term_organism",
    "score", "n_articles", "n_direct_articles", "dominant_label", "dominant_label_articles",
)


def export_hits(norm_path: Path, out_dir: Path, threads: int = 8, memory_limit: str = "24GB") -> list[Path]:
    """Writes hits_<type>.tsv.gz per entity type in one pass over the .norm file."""
    import duckdb

    out_dir.mkdir(parents=True, exist_ok=True)
    partition_dir = out_dir / "hits_partitions"
    shutil.rmtree(partition_dir, ignore_errors=True)

    duck = duckdb.connect()
    duck.execute(f"PRAGMA threads={threads}")
    duck.execute(f"PRAGMA memory_limit='{memory_limit}'")
    logger.info("Exporting normalized hits from %s", norm_path)
    duck.execute(
        f"""COPY ({_HITS_SQL}) TO '{partition_dir}'
            (FORMAT csv, DELIMITER '\t', HEADER true, COMPRESSION gzip, PARTITION_BY (entity_type))""",
        [str(norm_path)],
    )
    duck.close()

    # PARTITION_BY writes entity_type=<TYPE>/data_0.csv.gz and leaves the column out of the files
    written = []
    for part in sorted(partition_dir.glob("entity_type=*")):
        files = list(part.glob("*.csv.gz"))
        if len(files) != 1:
            raise RuntimeError(f"expected one file in {part}, found {len(files)}")
        target = out_dir / f"hits_{part.name.split('=', 1)[1].lower()}.tsv.gz"
        files[0].replace(target)
        written.append(target)
        logger.info("  %s: %.1f MB", target.name, target.stat().st_size / 1e6)
    shutil.rmtree(partition_dir)
    return written


def export_associations(con: sqlite3.Connection, out_dir: Path) -> Path:
    """Writes associations.tsv.gz: every association, with an empty label where there is none."""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "associations.tsv.gz"
    with gzip.open(target, "wt", newline="", compresslevel=6) as f:
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(_ASSOCIATION_COLUMNS)
        n = 0
        cursor = con.execute(_ASSOCIATIONS_SQL)
        while rows := cursor.fetchmany(100_000):
            writer.writerows(tuple(r) for r in rows)
            n += len(rows)
    logger.info("Exported %d association(s) to %s (%.1f MB)", n, target, target.stat().st_size / 1e6)
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Write the download files of an existing build.")
    parser.add_argument("--run", default="new_full_run_w_genes", help="run name: reads outputs/<run>/<run>.norm")
    parser.add_argument("--run-dir", type=Path, help="directory holding the run's files (default: outputs/<run>)")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="database to read (default: db/atlas.db)")
    parser.add_argument("--out", type=Path, help="output directory (default: downloads/ next to the database)")
    args = parser.parse_args()

    out_dir = args.out or args.db.parent / "downloads"
    setup_logging(output_dir=out_dir, run_name='exports_log')
    export_hits((args.run_dir or OUTPUTS_DIR / args.run) / f'{args.run}.norm', out_dir)
    export_associations(open_readonly(args.db), out_dir)
