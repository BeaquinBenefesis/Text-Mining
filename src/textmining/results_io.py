import csv
from pathlib import Path
from typing import Iterable, Iterator, Optional

import duckdb

from textmining.article_utils import ArticleRecord
from textmining.models import NormalizedHit, NormalizationResult, Association
from textmining.scoring import HitScore
from textmining.enums import HitType, SynonymType, NormalizationStatus, NormalizationTargetType

NORM_FIELDNAMES = [
    "sentence_id",
    "entity_type",
    "synonym_type",
    "synonym_id",
    "entity_id",
    "raw_text",
    "start_position",
    "hit_length",
    "synonym",
    "prefix",
    "suffix",
    "norm_status",
    "normalized_id",
    "target_type",
    "dead",
    "score",
]

# Matches NormalizedHit.sort_key; _tap_order enforces this exact total order.
_NORM_ORDER_BY = """
    split_part(sentence_id, '.', 1),
    CAST(split_part(sentence_id, '.', 2) AS INT),
    CAST(split_part(sentence_id, '.', 3) AS INT),
    start_position,
    hit_length
"""


def write_normalized_hits_tsv(articles: Iterable[ArticleRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = NORM_FIELDNAMES

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for article in articles:
            for hit in article.normalized_hits:
                writer.writerow(hit.to_dict())


def _as_str(value) -> Optional[str]:
    """csv yields '' for a missing field, duckdb yields None."""
    return value if value not in (None, "") else None


def _as_int(value) -> Optional[int]:
    return None if value in (None, "") else int(value)


def _as_float(value) -> Optional[float]:
    return None if value in (None, "") else float(value)


def _as_bool(value) -> bool:
    return value if isinstance(value, bool) else value == "True"


def _row_to_normalized_hit(row: dict) -> NormalizedHit:
    normalization = NormalizationResult(
        status=NormalizationStatus[row["norm_status"]] if row["norm_status"] else None,
        normalized_id=_as_str(row["normalized_id"]),
        target_type=NormalizationTargetType[row["target_type"]] if row["target_type"] else None,
        dead=_as_bool(row["dead"]),
    )
    return NormalizedHit(
        entity_type=HitType[row["entity_type"]] if row["entity_type"] else None,
        synonym_type=SynonymType[row["synonym_type"]] if row["synonym_type"] else None,
        sentence_id=row["sentence_id"],
        entity_id=row["entity_id"],
        raw_text=row["raw_text"],
        start_position=_as_int(row["start_position"]),
        hit_length=_as_int(row["hit_length"]),
        prefix=_as_str(row["prefix"]),
        suffix=_as_str(row["suffix"]),
        synonym=_as_str(row["synonym"]),
        synonym_id=_as_str(row["synonym_id"]),
        normalization=normalization,
        score=HitScore(_as_float(row["score"])) if _as_float(row["score"]) is not None else None,
    )


def read_normalized_hits(norm_hits_pattern: str, batch_size: int = 10_000) -> Iterator[NormalizedHit]:
    """Stream hits from one or more .norm files (glob allowed), sorted by sort_key.

    A fresh read of several shards carries no ordering guarantee, which both
    Grouper.group_by_sentence and AssociationEvidence depend on; duckdb supplies
    the out-of-core sort. The sort is blocking - nothing is yielded until the
    whole input has been read.
    """
    columns = ", ".join(NORM_FIELDNAMES)
    result = duckdb.execute(
        f"""
        SELECT {columns}
        FROM read_csv(?, delim='\t', header=true)
        ORDER BY {_NORM_ORDER_BY}
        """,
        [norm_hits_pattern],
    )
    while batch := result.fetchmany(batch_size):
        for row in batch:
            yield _row_to_normalized_hit(dict(zip(NORM_FIELDNAMES, row)))


def read_normalized_hits_tsv(input_path: Path) -> Iterator[NormalizedHit]:
    with input_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            yield _row_to_normalized_hit(row)

def write_associations_tsv(associations: Iterable[Association], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "normalized_id_a",
        "normalized_id_b",
        "entity_type_a",
        "entity_type_b",
        "score",
    ]

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for assoc in associations:
            writer.writerow({
                "normalized_id_a": assoc.normalized_ids[0],
                "normalized_id_b": assoc.normalized_ids[1],
                "entity_type_a": assoc.entity_types[0].name,
                "entity_type_b": assoc.entity_types[1].name,
                "score": f"{assoc.score:.4f}",
            })