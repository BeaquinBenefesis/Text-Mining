import sqlite3
from pathlib import Path
from typing import Iterator
from textmining.enums import HitType
from textmining.ontology import OntologyGraph
from textmining.models import Association
from textmining.db.loaders.entity import load_accession_to_id
from textmining.results_io import read_associations_tsv

def load_associations(con: sqlite3.Connection, associations_path: Path):
    associations = read_associations_tsv(associations_path)
    accession_to_id = load_accession_to_id(con)
    rows = (
        {
            'mirna_entity_id': accession_to_id[assoc.normalized_ids[0]],
            'term_entity_id': _term_entity_id(accession_to_id, assoc),
            'term_type': assoc.entity_types[1].value,
            'score': assoc.score,
            'evidence_mass': assoc.evidence_mass,
            'n_articles': assoc.n_articles,
            'n_direct_articles': assoc.n_direct_articles,
        }
        # NOTE: This skips dead mirnas, as they get no association accession.
        # The user can inspect the ambiguity inside the UI, but won't get any association data
        for assoc in associations if accession_to_id.get(assoc.normalized_ids[0], None)
    )
    con.executemany("""INSERT INTO association
                (mirna_entity_id, term_entity_id, term_type, score, evidence_mass, n_articles, n_direct_articles)
                VALUES (:mirna_entity_id, :term_entity_id, :term_type, :score, :evidence_mass, :n_articles, :n_direct_articles)""",
                rows
                )


def load_association_labels(con: sqlite3.Connection):
    """Label breakdown per association, from its evidence: an article (sentence) counts
    once for a label if at least one of its mention pairs has that as top label.

    Direct evidence only: propagated associations have no association_evidence rows.
    Needs association_evidence and mention_pair, so it runs after load_corpus."""
    con.execute("""INSERT INTO association_label (association_id, label, n_articles, n_sentences)
                SELECT ae.association_id, mp.label, count(DISTINCT s.article_id), count(DISTINCT ae.sentence_id)
                FROM association_evidence ae
                JOIN mention_pair mp ON mp.id = ae.mention_pair_id
                JOIN sentence s ON s.id = ae.sentence_id
                WHERE mp.label IS NOT NULL
                GROUP BY ae.association_id, mp.label""")
    # Dominant label: the specific label with the most articles; 'associated' only
    # if there is no specific one; never 'none'.
    con.execute("""UPDATE association SET (dominant_label, dominant_label_articles) = (
                    SELECT label, n_articles FROM association_label
                    WHERE association_id = association.id AND label != 'none'
                    ORDER BY label = 'associated', n_articles DESC, n_sentences DESC, label LIMIT 1)""")


def _term_entity_id(accession_to_id: dict[str, int], assoc: Association) -> int:
    term_id = assoc.normalized_ids[1]
    if term_id not in accession_to_id:
        raise KeyError(
            f"{assoc.entity_types[1].value} id {term_id!r} has no entity row: the run was produced with "
            "another ontology or synonym file than this build loads (for genes: resources.GENE_SYNS)"
        )
    return accession_to_id[term_id]
