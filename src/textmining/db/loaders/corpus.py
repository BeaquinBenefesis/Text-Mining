import sqlite3
from pathlib import Path
from typing import Iterator
from textmining.article_utils import MultiArticleReader
from textmining.sentence_utils import parse_sentence_id
from textmining.enums import Label
from textmining.models import CoOccurence, PairLabels
from textmining.db.loaders.entity import load_accession_to_id
from textmining.results_io import read_aligned_cooc_labels


# Load sentences, articles, association evidence

def load_corpus(
    con: sqlite3.Connection,
    coocs_path: Path,
    label_path: Path,
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
    labeld_coocs = read_aligned_cooc_labels(cooc_path=coocs_path, label_path=label_path)
    mention_pair_ids: dict[tuple, int] = {}   # mention_key -> mention_pair.id, of the current sentence only

    for cooc, labels in labeld_coocs:
        mirna_accession, term_accession = cooc.normalized_ids
        

        if mirna_accession not in accession_to_id:
            continue
        
        assoc_id = assoc_ids[(accession_to_id[mirna_accession], accession_to_id[term_accession])]

        if cooc.sentence_id not in sentence_ids:
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
            mention_pair_ids.clear()   # the rows of a sentence are contiguous

        sentence_id = sentence_ids[cooc.sentence_id]
        # one mention pair backs several co-occurrences (id combinations): insert it once
        if labels.mention_key not in mention_pair_ids:
            mention_pair_ids[labels.mention_key] = insert_mention_pair_row(con, sentence_id, labels)
        insert_association_evidence_row(con, sentence_id, assoc_id, mention_pair_ids[labels.mention_key], cooc)

    return sentence_ids


def insert_association_evidence_row(con: sqlite3.Connection, sentence_id: int, assoc_id: int, mention_pair_id: int, cooc: CoOccurence):
    mirna_position, term_position = cooc.entity_positions

    
    con.execute("""INSERT INTO association_evidence (association_id, mention_pair_id, sentence_id, mirna_start, mirna_end, term_start, term_end)
                VALUES (:association_id, :mention_pair_id, :sentence_id, :mirna_start, :mirna_end, :term_start, :term_end)""",
                {
                    "association_id": assoc_id,
                    "mention_pair_id": mention_pair_id,
                    "sentence_id": sentence_id,
                    "mirna_start": mirna_position[0],
                    "mirna_end": mirna_position[1],
                    "term_start": term_position[0],
                    "term_end": term_position[1]
                })

def insert_mention_pair_row(con: sqlite3.Connection, sentence_id: int, pair_labels: PairLabels) -> int:
    """Inserts one mention pair and returns its id. The label and the probabilities
    are NULL for a pair that could not be labelled."""
    mirna_positions, term_positions = pair_labels.entity_positions

    probabilities = pair_labels.probabilities or {}
    p_labels = {
        f"p_{l.value}": probabilities.get(l) for l in Label
    }
    max_prob_label = max(probabilities, key=probabilities.get).value if probabilities else None

    cursor = con.execute("""INSERT INTO mention_pair(sentence_id, mirna_start, mirna_end, term_start, term_end, term_type, label, confidence, p_none, p_associated, p_biomarker, p_expressed, p_expression_up, p_expression_down, p_inhibits, p_promotes, p_targets)
                    VALUES (:sentence_id, :mirna_start, :mirna_end, :term_start, :term_end, :term_type, :label, :confidence, :p_none, :p_associated, :p_biomarker, :p_expressed, :p_expression_up, :p_expression_down, :p_inhibits, :p_promotes, :p_targets)""",
                {
                    "sentence_id": sentence_id,
                    "mirna_start": mirna_positions[0],
                    "mirna_end": mirna_positions[1],
                    "term_start": term_positions[0],
                    "term_end": term_positions[1],
                    "term_type": pair_labels.term_type.value,
                    "label": max_prob_label,
                    "confidence": max(probabilities.values(), default=None),
                    **p_labels
                })
    return cursor.lastrowid



def _get_assoc_ids(con: sqlite3.Connection):
    rows = con.execute("SELECT mirna_entity_id, term_entity_id, id FROM association").fetchall()
    return {
        (mirna_entity_id, term_entity_id): id for mirna_entity_id, term_entity_id, id in rows
    }