import csv
import sys
import sqlite3
from pathlib import Path

csv.field_size_limit(sys.maxsize)

#TODO: check this is working as promised. I want to calculate the % of articles i can actually retrieve the date for
def _year_from_pubdate(pubdate: str) -> int | None:
    year_str = pubdate[:4]
    return int(year_str) if year_str.isdigit() else None


def load_article_metadata(
    con: sqlite3.Connection,
    pubmed_metadata_path: Path,
    pmc_metadata_path: Path,
) -> None:
    """Backfills article.year/journal from the two external metadata files.
    Only articles already present in `article` are looked up -- streams both
    files once each rather than loading either fully into memory."""
    rows = con.execute("SELECT id, external_id FROM article").fetchall()
    pmc_needed = {external_id: id for id, external_id in rows if external_id.startswith("PMC")}
    pubmed_needed = {external_id: id for id, external_id in rows if not external_id.startswith("PMC")}

    updates = []

    with pmc_metadata_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            article_id = pmc_needed.get(row["PMCID"])
            if article_id is None:
                continue
            updates.append({
                "id": article_id,
                "year": _year_from_pubdate(row["PubDate"]),
                "journal": row["Journal"] or None,
            })

    with pubmed_metadata_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            article_id = pubmed_needed.get(row["PMID"])
            if article_id is None:
                continue
            updates.append({
                "id": article_id,
                "year": _year_from_pubdate(row["PubDate"]),
                "journal": row["Journal"] or None,
            })

    con.executemany(
        "UPDATE article SET year = :year, journal = :journal WHERE id = :id",
        updates,
    )
