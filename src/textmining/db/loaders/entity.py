import logging
import re
import sqlite3

from textmining.config import MirbaseResources
from textmining.mirbase import load_mirbase
from textmining.enums import HitType
from textmining.ontology import OntologyGraph
from textmining.resources import ONTOLOGY_SOURCES, EXTRACTABLE_SYNONYMS
from textmining.ontology import to_external_id
from textmining.db.loaders.mirna_history import latest_row_per_accession

logger = logging.getLogger(__name__)

_ENTITY_INSERT = """INSERT INTO entity
    (accession, primary_name, entity_type, source, obsolete, reference_level, organism)
    VALUES (:accession, :primary_name, :entity_type, :source, :obsolete, :reference_level, :organism)"""

# miRBase prefixes run 3-7 characters ('hsa', 'kshv', 'ptvpv2a'); 277 distinct
# prefixes appear in the history files and all but two fit [a-z][a-z0-9]{2,4},
# so the bound is widened rather than special-cased.
_ORGANISM_RE = re.compile(r"^[a-z][a-z0-9]{2,6}$")


def organism_from_name(primary_name: str, reference_level: str | None) -> str | None:
    """miRBase encodes the organism as the segment before the first '-'.

    Families are excluded on purpose: they are cross-species by definition and
    their names carry no prefix ('let-7', 'mir-17'), so the first segment would
    parse as the bogus organisms 'let' and 'mir'.
    """
    if reference_level not in ("mature", "precursor"):
        return None
    prefix, sep, _ = primary_name.partition("-")
    if not sep:
        return None
    return prefix if _ORGANISM_RE.fullmatch(prefix) else None


def load_entities(
    con: sqlite3.Connection,
    mirbase: MirbaseResources,
    ontology_graphs: dict[HitType, OntologyGraph],
    history_rows: list[dict] | None = None,
):
    _, nodes, _ = load_mirbase(
        families_tsv=mirbase.families_path,
        precursors_tsv=mirbase.precursor_path,
        mature_tsv=mirbase.mature_path,
        parent_to_child_tsv=mirbase.parent_to_child_path,
    )

    # The mapping TSVs carry no dead/obsolete signal; the history files do.
    latest = latest_row_per_accession(history_rows or [])

    con.executemany(
        _ENTITY_INSERT,
        [
            {
                "accession": node["accession"],
                "primary_name": node["name"],
                "entity_type": HitType.MIR.value,
                "source": "mirbase",
                "obsolete": latest.get(node["accession"], {}).get("dead", 0),
                "reference_level": node["type"],
                "organism": organism_from_name(node["name"], node["type"]),
            }
            for node in nodes.values()
        ],
    )
    logger.info("Loaded %d miRBase entity row(s)", len(nodes))

    ontology_roots = {
        entity_type: [r for spec in specs for r in spec.roots]
        for entity_type, specs in EXTRACTABLE_SYNONYMS.items()
    }

    for entity_type, graph in ontology_graphs.items():
        con.executemany(
            _ENTITY_INSERT,
            [
                {
                    "accession": to_external_id(node["id"]),
                    "primary_name": node["name"],
                    "entity_type": entity_type.value,
                    "source": ONTOLOGY_SOURCES[entity_type].source,
                    "obsolete": 0,
                    "reference_level": None,
                    "organism": None,
                }
                for node in graph.iter_nodes(ontology_roots.get(entity_type, None))
                if node.get("name")
            ],
        )

    if history_rows:
        _load_retired_accessions(con, latest, set(nodes))


def _load_retired_accessions(con: sqlite3.Connection, latest: dict[str, dict], known: set[str]):
    """Insert accessions that appear in the miRBase history but not in the current
    mapping files -- they were retired before the shipped release.

    Without these an ID-conflict page has nothing to render for whichever side of
    the conflict is no longer current, which is frequently the interesting side.
    """
    missing = [
        {
            "accession": accession,
            "primary_name": row["mirna_name"],
            "entity_type": HitType.MIR.value,
            "source": "mirbase",
            "obsolete": 1,
            "reference_level": row["reference_level"],
            "organism": organism_from_name(row["mirna_name"], row["reference_level"]),
        }
        for accession, row in latest.items()
        if accession not in known
    ]
    con.executemany(_ENTITY_INSERT, missing)
    logger.info("Loaded %d retired miRBase accession(s) as obsolete", len(missing))


def load_accession_to_id(con: sqlite3.Connection) -> dict[str, int]:
    rows = con.execute("SELECT accession, id FROM entity").fetchall()
    return {accession: id for accession, id in rows}
