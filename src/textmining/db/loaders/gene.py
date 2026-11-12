"""Genes have no ontology: their entities and synonyms come from the syngrep
dictionary itself, keyed by the composite id the pipeline writes into the
.assoc/.cooc files ('KIT@HUGO|3815@LOCUSLINK|KIT_HUMAN@SWISSPROT').
"""
import json
import logging
import sqlite3
from pathlib import Path
from typing import Iterator

from textmining.enums import HitType
from textmining.db.loaders.entity import _ENTITY_INSERT, load_accession_to_id
from textmining.synonym_utils import CASE_SENS_TAG

logger = logging.getLogger(__name__)


def read_gene_records(path: Path) -> Iterator[tuple[str, list[str]]]:
    """(gene id, synonyms) per line of a .syn file, syngrep tags removed."""
    with open(path) as f:
        for line in f:
            gene_id, sep, synonyms = line.rstrip("\n").partition(":")
            if not sep:
                continue
            yield gene_id, [s.removesuffix(CASE_SENS_TAG) for s in synonyms.split("|") if s]


def load_gene_entities(con: sqlite3.Connection, syn_path: Path, raw_syn_path: Path, organism_map_path: Path):
    """One entity per record of the filtered dictionary.

    The name is the first synonym of the unfiltered dictionary, which is the gene
    symbol. The filtered record cannot supply it: the stoplist removes the symbol
    of some genes (ACE, KIT), leaving a description or an alias in first place.
    """
    symbols = {gene_id: synonyms[0] for gene_id, synonyms in read_gene_records(raw_syn_path) if synonyms}
    with open(organism_map_path) as f:
        organisms = json.load(f)

    rows = [
        {
            "accession": gene_id,
            "primary_name": symbols.get(gene_id, synonyms[0]),
            "entity_type": HitType.GENE.value,
            "source": "gene_dictionary",
            "obsolete": 0,
            "reference_level": None,
            "organism": organisms.get(gene_id),
            "ic": None,
        }
        for gene_id, synonyms in read_gene_records(syn_path)
    ]
    con.executemany(_ENTITY_INSERT, rows)
    logger.info("Loaded %d gene entity row(s)", len(rows))


def load_gene_synonyms(con: sqlite3.Connection, syn_path: Path):
    accession_to_id = load_accession_to_id(con)
    rows = (
        {"synonym_name": synonym, "synonym_type": "STANDARD", "entity_id": accession_to_id[gene_id]}
        for gene_id, synonyms in read_gene_records(syn_path)
        for synonym in dict.fromkeys(synonyms)
    )
    cursor = con.executemany(
        """INSERT INTO synonym (synonym_name, synonym_type, entity_id)
           VALUES (:synonym_name, :synonym_type, :entity_id)""",
        rows,
    )
    logger.info("Loaded %d gene synonym(s)", cursor.rowcount)
