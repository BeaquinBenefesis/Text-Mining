import csv
from pathlib import Path
from typing import Iterable, Iterator
from textmining.article_utils import ArticleRecord
from textmining.models import NormalizedHit, NormalizationResult
from textmining.scoring import HitScore
from textmining.types import HitType, SynonymType, NormalizationStatus, NormalizationTargetType

def write_normalized_hits_tsv(articles: Iterable[ArticleRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
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

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for article in articles:
            for hit in article.normalized_hits:
                writer.writerow(hit.to_dict())


def _row_to_normalized_hit(row: dict) -> NormalizedHit:
    normalization = NormalizationResult(
        status=NormalizationStatus[row["norm_status"]] if row["norm_status"] else None,
        normalized_id=row["normalized_id"] or None,
        target_type=NormalizationTargetType[row["target_type"]] if row["target_type"] else None,
        dead=row["dead"] == "True",
    )
    return NormalizedHit(
        entity_type=HitType[row["entity_type"]] if row["entity_type"] else None,
        synonym_type=SynonymType[row["synonym_type"]] if row["synonym_type"] else None,
        sentence_id=row["sentence_id"],
        entity_id=row["entity_id"],
        raw_text=row["raw_text"],
        start_position=int(row["start_position"]),
        hit_length=int(row["hit_length"]),
        prefix=row["prefix"] or None,
        suffix=row["suffix"] or None,
        synonym=row["synonym"] or None,
        synonym_id=row["synonym_id"] or None,
        normalization=normalization,
        score=HitScore(float(row["score"])) if row["score"] else None,
    )


def read_normalized_hits_tsv(input_path: Path) -> Iterator[NormalizedHit]:
    with input_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            yield _row_to_normalized_hit(row)
