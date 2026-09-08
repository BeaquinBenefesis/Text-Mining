import csv
from pathlib import Path
from typing import Iterable, Iterator, NamedTuple, Optional

import duckdb

from textmining.article_utils import ArticleRecord
from textmining.models import NormalizedHit, NormalizationResult, Association, CoOccurence
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

# Matches NormalizedHit.sort_key;
_NORM_ORDER_BY = """
    split_part(sentence_id, '.', 1),
    CAST(split_part(sentence_id, '.', 2) AS INT),
    CAST(split_part(sentence_id, '.', 3) AS INT),
    start_position,
    hit_length
"""


def write_normalized_hits_tsv(normalized_hits: Iterable[NormalizedHit], output_path: Path) -> Iterable[NormalizedHit]:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = NORM_FIELDNAMES

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for hit in normalized_hits:
            writer.writerow(hit.to_dict())
            yield hit


COOC_FIELDNAMES = [
    "article_id",
    "sentence_id",
    "section_num",
    "origin_file_name",
    "normalized_id_a",
    "normalized_id_b",
    "entity_type_a",
    "entity_type_b",
    "start_a",
    "end_a",
    "start_b",
    "end_b",
    "weight",
]


def write_cooccurrences_tsv(cooccurrences: Iterable[CoOccurence], output_path: Path) -> Iterator[CoOccurence]:
    """Pass-through writer: consumes lazily and re-yields, like write_normalized_hits_tsv."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COOC_FIELDNAMES, delimiter="\t")
        writer.writeheader()
        for cooc in cooccurrences:
            (start_a, end_a), (start_b, end_b) = cooc.entity_positions
            writer.writerow({
                "article_id": cooc.article_id,
                "sentence_id": cooc.sentence_id,
                "section_num": cooc.section_num,
                "origin_file_name": cooc.origin_file_name,
                "normalized_id_a": cooc.normalized_ids[0],
                "normalized_id_b": cooc.normalized_ids[1],
                "entity_type_a": cooc.entity_types[0].name,
                "entity_type_b": cooc.entity_types[1].name,
                "start_a": start_a,
                "end_a": end_a,
                "start_b": start_b,
                "end_b": end_b,
                "weight": cooc.weight,
            })
            yield cooc


def read_cooccurrences_tsv(input_path: Path) -> Iterator[CoOccurence]:
    """Reads a .cooc file back into CoOccurence objects. article_epoch is not
    persisted (it's a live-run-only bookkeeping value for ArticleStreamGuard,
    meaningless once reloaded), so it's stamped as 0 here -- callers reading
    this back are past the aggregation stage and never use it."""
    with input_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            yield CoOccurence(
                article_id=row["article_id"],
                sentence_id=row["sentence_id"],
                section_num=row["section_num"],
                origin_file_name=_as_str(row["origin_file_name"]),
                article_epoch=0,
                normalized_ids=(row["normalized_id_a"], row["normalized_id_b"]),
                entity_types=(HitType[row["entity_type_a"]], HitType[row["entity_type_b"]]),
                entity_positions=(
                    (_as_int(row["start_a"]), _as_int(row["end_a"])),
                    (_as_int(row["start_b"]), _as_int(row["end_b"])),
                ),
                weight=_as_int(row["weight"]),
            )


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


class ReadAssociation(NamedTuple):
    """Duck-typed stand-in for Association, not the real thing -- Association.score
    is a computed property over AssociationEvidence's private log-sum state, which
    a single stored float can't reconstruct. load_associations only ever reads
    .normalized_ids/.entity_types/.score, so this is a drop-in for that purpose."""
    normalized_ids: tuple[str, str]
    entity_types: tuple[HitType, HitType]
    score: float


def read_associations_tsv(input_path: Path) -> Iterator[ReadAssociation]:
    with input_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            yield ReadAssociation(
                normalized_ids=(row["normalized_id_a"], row["normalized_id_b"]),
                entity_types=(HitType[row["entity_type_a"]], HitType[row["entity_type_b"]]),
                score=float(row["score"]),
            )