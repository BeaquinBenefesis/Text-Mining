import csv
from pathlib import Path
from typing import Iterable
from textmining.article_utils import ArticleRecord

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
