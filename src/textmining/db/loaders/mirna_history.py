"""miRBase name history: the per-release record of which accession carried which
name. Two consumers:

  * `load_mirna_name_history` fills `mirna_name_history`, which backs the
    disambiguation view for names whose referent changed between releases.
  * `read_history` / `conflicted_names` are read by `loaders/entity.py` (dead
    accessions, `obsolete`) and `loaders/synonym.py` (legacy surface forms).

The files are a superset of `*_id_conflicts.tsv`: conflicted names are exactly
those mapping to more than one accession here. Deriving them means the conflict
files are not needed as a separate input -- which also sidesteps the duplicated
header row those two files carry.
"""
import csv
import logging
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"^v(\d+)(?:_(\d+))?$")


def version_rank(version: str) -> int:
    """'v9_2' -> 9002, 'v10' -> 10000. Lexical order on the raw string is wrong
    ('v10' < 'v9'), and the UI has to render version ranges in release order."""
    match = _VERSION_RE.match(version.strip())
    if not match:
        logger.warning("Unparseable miRBase version %r, sorting it last", version)
        return 10**9
    major, minor = match.group(1), match.group(2)
    return int(major) * 1000 + (int(minor) if minor else 0)


def read_history(path: Path, reference_level: str) -> list[dict]:
    """One dict per (name, accession, version) row of a history TSV."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [
            {
                "mirna_name": row["mirna_name"],
                "accession": row["accession"],
                "version": row["version"],
                "version_rank": version_rank(row["version"]),
                "dead": int(row["dead"].strip().upper() == "TRUE"),
                "reference_level": reference_level,
            }
            for row in csv.DictReader(handle, delimiter="\t")
        ]
    logger.info("Read %d history row(s) from %s", len(rows), path.name)
    return rows


def name_to_accessions(rows: list[dict]) -> dict[tuple[str, str], set[str]]:
    """(reference_level, lowercased name) -> every accession that carried it.

    The level must stay in the key. miRBase distinguishes a precursor from its
    mature product by capitalisation alone -- `hsa-mir-34b` is the hairpin,
    `hsa-miR-34b` the mature strand -- so casefolding a combined list collapses
    the two namespaces and reports every such pair as an ID conflict. Grouping
    within a level reproduces the 274 real conflicts; grouping across them
    produced 24,768.
    """
    mapping = defaultdict(set)
    for row in rows:
        mapping[(row["reference_level"], row["mirna_name"].lower())].add(row["accession"])
    return mapping


def conflicted_names(rows: list[dict]) -> set[str]:
    """Lowercased names that more than one accession carried *within one level*.

    These are the names MirNormalizer marks IN_BLACKLIST (it checks
    `ambiguous_precursors` and `ambiguous_mature` as separate sets for exactly
    this reason). They must never be resolved to a single entity -- they route to
    the disambiguation view instead.
    """
    return {
        name
        for (_level, name), accessions in name_to_accessions(rows).items()
        if len(accessions) > 1
    }


def latest_row_per_accession(rows: list[dict]) -> dict[str, dict]:
    """Accession -> its row from the most recent release it appears in. Both the
    current name and the current `dead` status come from this row; an accession
    dead in v12 but revived later must not be reported as obsolete."""
    best: dict[str, dict] = {}
    for row in rows:
        current = best.get(row["accession"])
        if current is None or row["version_rank"] > current["version_rank"]:
            best[row["accession"]] = row
    return best


def load_mirna_name_history(con: sqlite3.Connection, history_rows: list[dict]) -> None:
    con.executemany(
        """INSERT OR IGNORE INTO mirna_name_history
               (mirna_name, accession, version, version_rank, dead, reference_level)
           VALUES (:mirna_name, :accession, :version, :version_rank, :dead, :reference_level)""",
        history_rows,
    )
    logger.info("Loaded %d mirna_name_history row(s)", len(history_rows))
