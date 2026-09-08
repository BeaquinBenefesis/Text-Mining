import sqlite3
from pathlib import Path
from typing import Iterator
from textmining.article_utils import MultiArticleReader
from textmining.sentence_utils import parse_sentence_id
from textmining.models import CoOccurence
from textmining.db.loaders.entity import load_accession_to_id
from textmining.results_io import read_cooccurrences_tsv

# Load sentences, articles, association evidence

def load_corpus(
    con: sqlite3.Connection,
    coocs_path: Path,
    reader: MultiArticleReader,
) -> dict[str, int]:
    """Populates article/sentence with exactly the sentences coocs needs.
    Returns sentence_id -> sentence.id, for the association_evidence loader to
    resolve its sentence_id FK against."""
    article_ids: dict[str, int] = {}
    sentence_ids: dict[str, int] = {}
    article_cache: dict[tuple[str, str], dict[str, str]] = {}
    assoc_ids: dict[tuple[int, int], int] = _get_assoc_ids(con)
    accession_to_id: dict[str, int] = load_accession_to_id(con)
    coocs = read_cooccurrences_tsv(coocs_path)
    
    for cooc in coocs:
        mirna_accession, term_accession = cooc.normalized_ids
        assoc_id = assoc_ids[(accession_to_id[mirna_accession], accession_to_id[term_accession])]

        if cooc.sentence_id in sentence_ids:
            insert_association_evidence_row(con, sentence_ids[cooc.sentence_id], assoc_id, cooc)
            continue

        article_id, section_num, sentence_num = parse_sentence_id(cooc.sentence_id)

        if article_id not in article_ids:
            cursor = con.execute(
                "INSERT INTO article (external_id) VALUES (?)", (article_id,)
            )
            article_ids[article_id] = cursor.lastrowid

        cache_key = (cooc.origin_file_name, article_id)
        if cache_key not in article_cache:
            article_cache[cache_key] = reader.fetch_article(cooc.origin_file_name, article_id)
        text = article_cache[cache_key][cooc.sentence_id]

        cursor = con.execute(
            """INSERT INTO sentence (article_id, section_num, sentence_num, sentence_text)
               VALUES (:article_id, :section_num, :sentence_num, :sentence_text)""",
            {
                "article_id": article_ids[article_id],
                "section_num": section_num,
                "sentence_num": sentence_num,
                "sentence_text": text,
            },
        )
        sentence_ids[cooc.sentence_id] = cursor.lastrowid
        insert_association_evidence_row(con, sentence_ids[cooc.sentence_id], assoc_id, cooc)

    return sentence_ids


def insert_association_evidence_row(con: sqlite3.Connection, sentence_id: int, assoc_id: int, cooc: CoOccurence):
    mirna_position, term_position = cooc.entity_positions

    
    con.execute("""INSERT INTO association_evidence (association_id, sentence_id, mirna_start, mirna_end, term_start, term_end)
                VALUES (:association_id, :sentence_id, :mirna_start, :mirna_end, :term_start, :term_end)""",
                {
                    "association_id": assoc_id,
                    "sentence_id": sentence_id,
                    "mirna_start": mirna_position[0],
                    "mirna_end": mirna_position[1],
                    "term_start": term_position[0],
                    "term_end": term_position[1]
                })

def _get_assoc_ids(con: sqlite3.Connection):
    rows = con.execute("SELECT mirna_entity_id, term_entity_id, id FROM association").fetchall()
    return {
        (mirna_entity_id, term_entity_id): id for mirna_entity_id, term_entity_id, id in rows
    }