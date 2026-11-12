"""Read-only queries backing the UI. One function per panel; each takes an open
connection and returns plain dicts.

No ORM, matching the raw-SQL decision in notes/DATABASE_DESIGN_NOTES.txt section 8.1.
"""
import json
import sqlite3
from dataclasses import dataclass

from textmining.web.highlight import extend_mirna_span, render

PER_PAGE = 25
EVIDENCE_PER_PAGE = 20
CORPUS_TIMELINE_START = 2000  # earlier years hold almost no articles

TERM_TYPES = ("DISEASE", "BIOLOGICAL_PROCESS", "CELL", "PATHWAY", "TISSUE", "GENE")
# Lists show one term type at a time: relevance is not comparable across ontologies.
DEFAULT_TYPE = "DISEASE"
# Types without an ontology have no IC, hence no relevance: ordered by evidence only.
UNRANKED_TYPES = ("GENE",)
TYPE_PLURALS = {"DISEASE": "diseases", "BIOLOGICAL_PROCESS": "biological processes", "CELL": "cell types",
                "PATHWAY": "pathways", "TISSUE": "tissues", "GENE": "genes"}
LEVEL_PLURALS = {"mature": "mature miRNAs", "precursor": "precursors", "family": "families"}
LEVELS = ("mature", "precursor", "family")

# Ranking (notes/WEIGHTED_RANKING_PLAN.md). "relevance" orders by E * ic^alpha: the evidence
# mass before the outer log, discounted by normalised structural IC, so halving a
# term's IC costs 2^alpha times the evidence. alpha = 2 is provisional. "evidence"
# is the plain score. Only these fixed expressions reach SQL; the alpha constant is
# inlined, never user input.
RELEVANCE_ALPHA = 2
SORTS = ("relevance", "evidence")

# Relation labels (notes/RELATION_LABELS_PLAN.md), in display order: opposite pairs are adjacent.
# 'none' is not listed: it is never an association's dominant label.
LABELS = ("promotes", "inhibits", "expression_up", "expression_down", "targets",
          "expressed", "biomarker", "associated")
# The model's probability orders sentences reliably but is overconfident, so it is shown
# as a level. Cut-offs from the coverage table in analysis/training.ipynb.
CONFIDENCE_LEVELS = ((0.983, "high"), (0.85, "medium"))
EVIDENCE_SORTS = ("article", "confidence")


def confidence_level(confidence: float) -> str:
    return next((level for cutoff, level in CONFIDENCE_LEVELS if confidence >= cutoff), "low")


def _rank_key(sort: str, a: str = "a", e: str = "e") -> str:
    assert sort in SORTS, sort
    if sort == "relevance":
        return f"{a}.evidence_mass * pow({e}.ic, {RELEVANCE_ALPHA})"
    return f"{a}.score"


def _relevance(a: str = "a", e: str = "e") -> str:
    """Displayed relevance, log2(1 + ic^alpha * E): the same units as score, and
    never above it. NULL for terms without IC (stale ids on a dev database)."""
    return f"log2(1 + {a}.evidence_mass * pow({e}.ic, {RELEVANCE_ALPHA}))"


def _assoc_columns(a: str = "a", e: str = "e") -> str:
    return f"""{a}.id, {a}.score, {a}.term_type, {a}.evidence_mass,
               {a}.n_articles, {a}.n_direct_articles, {e}.ic,
               {a}.dominant_label, {a}.dominant_label_articles,
               {_relevance(a, e)} AS relevance"""


def _label_filter(label: str | None, a: str = "a") -> str:
    """Keeps the associations whose dominant label is :label. The same in every list."""
    return f" AND {a}.dominant_label = :label" if label else ""


def _rows(con, sql, params=()):
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def _one(con, sql, params=()):
    row = con.execute(sql, params).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- search

def search(con: sqlite3.Connection, query: str, limit: int = 30) -> list[dict]:
    """Prefix search over names, synonyms, legacy miRBase names and accessions.

    Ambiguous miRBase identifiers come back with entity_id NULL and kind
    'conflict'; the caller routes those to the disambiguation view instead of
    resolving them to one entity.
    """
    q = query.strip().lower()
    if not q:
        return []
    matches = _rows(con, """
        SELECT sn.display_name, sn.entity_id, sn.kind,
               e.accession, e.primary_name, e.entity_type, e.reference_level,
               e.organism, e.obsolete
        FROM search_name sn
        LEFT JOIN entity e ON e.id = sn.entity_id
        WHERE sn.name_lower >= :q AND sn.name_lower < :q || char(0x10FFFF)
        ORDER BY (sn.name_lower = :q) DESC, length(sn.name_lower), sn.name_lower
        LIMIT :lim
    """, {"q": q, "lim": limit * 4})

    seen, results = set(), []
    for row in matches:
        key = ("conflict", row["display_name"].lower()) if row["entity_id"] is None \
            else ("entity", row["entity_id"])
        if key in seen:
            continue
        seen.add(key)
        results.append(row)
        if len(results) >= limit:
            break
    return results


def get_entity(con: sqlite3.Connection, accession: str) -> dict | None:
    return _one(con, """
        SELECT id, accession, primary_name, entity_type, source, obsolete,
               reference_level, organism, ic
        FROM entity WHERE accession = ?
    """, (accession,))


# ---------------------------------------------------------------- timelines

def _normalise(rows: list[dict]) -> list[dict]:
    """Attach share-of-corpus alongside the raw count.

    The corpus is 98% post-2010 and 54% post-2020, so a raw per-year count is
    dominated by corpus composition; every miRNA shows the same rising shape.
    Dividing by that year's article total is what makes the series comparable
    across years.
    """
    for row in rows:
        corpus = row.get("corpus_articles") or 0
        row["share"] = row["n_articles"] / corpus if corpus else 0.0
    return rows


def mirna_timeline(con: sqlite3.Connection, mir_key: str) -> list[dict]:
    """Articles per year mentioning this miRNA -- from the mention layer, so it
    counts every mention, not only those that produced an association.

    `mir_key` is an accession for a normalised miRNA and a surface name for a
    blacklisted one, which is what lets the conflict view chart names that have
    no accession at all.
    """
    return _normalise(_rows(con, """
        SELECT a.year, count(*) AS n_articles, cy.n_articles AS corpus_articles
        FROM mir_mention_article m
        JOIN article a     ON a.id = m.article_id
        JOIN corpus_year cy ON cy.year = a.year
        WHERE m.mir_key = ?
        GROUP BY a.year ORDER BY a.year
    """, (mir_key,)))


def association_timeline(con: sqlite3.Connection, association_ids: list[int]) -> list[dict]:
    """Articles per year with evidence for any of these associations: an association and
    those of its subterms (association_subterms). Counted once however many of them an article names."""
    return _normalise(_rows(con, """
        SELECT a.year, count(DISTINCT s.article_id) AS n_articles,
               cy.n_articles AS corpus_articles
        FROM association_evidence ae
        JOIN sentence s     ON s.id = ae.sentence_id
        JOIN article a      ON a.id = s.article_id
        JOIN corpus_year cy ON cy.year = a.year
        WHERE ae.association_id IN (SELECT value FROM json_each(?))
        GROUP BY a.year ORDER BY a.year
    """, (json.dumps(association_ids),)))


# ---------------------------------------------------------------- miRNA stats

@dataclass
class MirnaStats:
    n_articles: int
    breadth: int
    # position by n_articles among the mentioned miRNAs of the same reference level
    # and organism; None for a miRNA that is never mentioned
    rank: int | None = None
    population: int | None = None

    @property
    def top_share(self) -> float | None:
        """Share of the population ranked at or above this miRNA, in (0, 1]."""
        return self.rank / self.population if self.rank else None


def mirna_stats(con: sqlite3.Connection, entity_id: int, mir_key: str) -> MirnaStats:
    """Articles mentioning a miRNA, its number of associated terms and its rank.

    Ranks are comparable only within a reference level: a precursor also collects
    the articles that name no arm, so it outranks its own mature forms.
    """
    n_articles = con.execute(
        "SELECT count(*) FROM mir_mention_article WHERE mir_key = ?", (mir_key,)
    ).fetchone()[0]
    breadth = con.execute(
        "SELECT count(DISTINCT term_entity_id) FROM association WHERE mirna_entity_id = ?",
        (entity_id,),
    ).fetchone()[0]
    try:
        rank, population = con.execute(
            "SELECT pop_rank, pop_size FROM mirna_stats WHERE entity_id = ?", (entity_id,)
        ).fetchone() or (None, None)
    except sqlite3.OperationalError:   # database built before mirna_stats existed
        rank = population = None
    return MirnaStats(n_articles, breadth, rank, population)


# ---------------------------------------------------------------- term clouds

def mirna_term_clouds(con, entity_id: int, per_type: int = 15, candidates: int = 60) -> list[dict]:
    """The most specific top terms of a miRNA, one panel per term type.

    Evidence is propagated to ontology ancestors, so the plain top rows of a type
    are chains ('breast cancer', 'thoracic cancer', 'cancer'). A candidate is
    dropped when one of its descendants is also a candidate, which leaves the
    most specific term of each chain.

    `weight` in [0, 1] is scaled within the panel: relevance is not comparable
    across ontologies, and genes have evidence only.
    """
    panels = []
    for term_type in TERM_TYPES:
        ranked = term_type not in UNRANKED_TYPES
        value = _relevance() if ranked else "a.score"
        terms = _rows(con, f"""
            SELECT a.id, a.term_entity_id, e.primary_name AS term_name, a.score, a.n_articles,
                   {value} AS value
            FROM association a JOIN entity e ON e.id = a.term_entity_id
            WHERE a.mirna_entity_id = ? AND a.term_type = ? AND {value} > 0
            ORDER BY value DESC, a.id LIMIT ?
        """, (entity_id, term_type, candidates))
        if not terms:
            continue
        if ranked:
            ids = [t["term_entity_id"] for t in terms]
            marks = ",".join("?" * len(ids))
            broader = {row[0] for row in con.execute(f"""
                SELECT DISTINCT ancestor_id FROM ontology_closure
                WHERE ancestor_id IN ({marks}) AND descendant_id IN ({marks})
            """, ids + ids)}
            terms = [t for t in terms if t["term_entity_id"] not in broader]
        terms = terms[:per_type]
        low, high = terms[-1]["value"], terms[0]["value"]
        for t in terms:
            t["weight"] = (t["value"] - low) / (high - low) if high > low else 1.0
        panels.append({"term_type": term_type, "terms": terms})
    return panels


# ---------------------------------------------------------------- associations

def mirna_association_counts(con: sqlite3.Connection, entity_id: int) -> dict[str, int]:
    return {
        row["term_type"]: row["n"]
        for row in _rows(con, """
            SELECT term_type, count(*) AS n FROM association
            WHERE mirna_entity_id = ? GROUP BY term_type
        """, (entity_id,))
    }


def mirna_associations(con, entity_id: int, term_type: str,
                       page: int = 1, per_page: int = PER_PAGE,
                       sort: str = "relevance", label: str | None = None) -> dict:
    where = "a.mirna_entity_id = :eid AND a.term_type = :tt" + _label_filter(label)
    params = {"eid": entity_id, "tt": term_type, "label": label,
              "lim": per_page, "off": (page - 1) * per_page}
    total = con.execute(f"SELECT count(*) FROM association a WHERE {where}", params).fetchone()[0]
    # Relevance order needs a temp sort after the ix_assoc_mir_score range scan:
    # ~6 ms for the largest miRNA (notes/WEIGHTED_RANKING_PLAN.md section 8).
    items = _rows(con, f"""
        SELECT {_assoc_columns()},
               e.accession AS term_accession, e.primary_name AS term_name,
               e.organism AS term_organism
        FROM association a
        JOIN entity e ON e.id = a.term_entity_id
        WHERE {where}
        ORDER BY {_rank_key(sort)} DESC, a.score DESC, a.id LIMIT :lim OFFSET :off
    """, params)
    return {"items": items, "total": total, "page": page, "per_page": per_page}


# The database is opened immutable, so a global listing cannot change while the
# process runs. Keyed by every argument; bounded so that paging through many
# filter combinations cannot grow it without limit.
_TOP_CACHE: dict[tuple, dict] = {}
_TOP_CACHE_MAX = 256


def top_associations(con, sort: str = "relevance", term_type: str = DEFAULT_TYPE,
                     organism: str | None = "hsa", level: str | None = "mature",
                     page: int = 1, per_page: int = PER_PAGE, label: str | None = None) -> dict:
    """All associations of one term type under one ordering, as a browsable list of examples.

    Deliberately not deduplicated: heavily studied miRNAs (miR-21, miR-155) repeat,
    and precursor and mature rows of one miRNA both appear when no level is chosen.
    Families carry no organism, so an organism filter excludes them.

    No index serves a global order by a computed key, so an uncached page is a
    scan with a top-N sort over every matching association.
    """
    key = (sort, term_type, organism, level, label, page, per_page)
    if key in _TOP_CACHE:
        return _TOP_CACHE[key]

    where = ["a.term_type = :tt" + _label_filter(label)]
    params = {"tt": term_type, "label": label, "lim": per_page, "off": (page - 1) * per_page}
    if organism:
        where.append("m.organism = :org"); params["org"] = organism
    if level:
        where.append("m.reference_level = :lvl"); params["lvl"] = level
    where_sql = " AND ".join(where)

    total_key = (sort, term_type, organism, level, label, "total")
    total = _TOP_CACHE.get(total_key)
    if total is None:
        total = con.execute(f"""
            SELECT count(*) FROM association a JOIN entity m ON m.id = a.mirna_entity_id
            WHERE {where_sql}
        """, params).fetchone()[0]
    items = _rows(con, f"""
        SELECT {_assoc_columns()},
               e.accession AS term_accession, e.primary_name AS term_name,
               e.organism AS term_organism,
               m.accession AS mirna_accession, m.primary_name AS mirna_name,
               m.reference_level, m.organism
        FROM association a
        JOIN entity m ON m.id = a.mirna_entity_id
        JOIN entity e ON e.id = a.term_entity_id
        WHERE {where_sql}
        ORDER BY {_rank_key(sort)} DESC, a.score DESC, a.id LIMIT :lim OFFSET :off
    """, params)

    result = {"items": items, "total": total, "page": page, "per_page": per_page}
    if len(_TOP_CACHE) >= _TOP_CACHE_MAX:
        _TOP_CACHE.clear()
    _TOP_CACHE[total_key] = total
    _TOP_CACHE[key] = result
    return result


def term_mirnas(con, term_entity_id: int, organism: str | None = "hsa",
                page: int = 1, per_page: int = PER_PAGE, label: str | None = None) -> dict:
    """miRNAs associated with a term, by evidence.

    One row per miRNA, and each row is exactly the association of that miRNA with
    this term: UNIQUE (mirna_entity_id, term_entity_id). Subtype evidence is already
    in the score through propagation (design notes 5.1b), so the ontology is not
    expanded again at query time. Listing a miRNA under its best descendant instead
    (5.1a) made a row stand for an association with some other term than the one
    looked up.

    Ordered by evidence only: the term's specificity is the same on every row, so
    relevance would give the same order.
    """
    org_filter = "AND m.organism = :org" if organism else ""
    params = {"tid": term_entity_id, "org": organism, "label": label,
              "lim": per_page, "off": (page - 1) * per_page}
    where = f"""
        FROM association a
        JOIN entity m ON m.id = a.mirna_entity_id
        WHERE a.term_entity_id = :tid {org_filter} {_label_filter(label)}
    """
    total = con.execute("SELECT count(*)" + where, params).fetchone()[0]
    items = _rows(con, f"""
        SELECT a.id, a.score, a.n_articles, a.n_direct_articles,
               a.dominant_label, a.dominant_label_articles,
               m.accession AS mirna_accession, m.primary_name AS mirna_name,
               m.reference_level, m.organism
        {where}
        ORDER BY a.score DESC, a.id LIMIT :lim OFFSET :off
    """, params)
    return {"items": items, "total": total, "page": page, "per_page": per_page}


def get_association(con: sqlite3.Connection, association_id: int) -> dict | None:
    return _one(con, f"""
        SELECT {_assoc_columns('a', 'te')},
               mi.id AS mirna_entity_id, mi.accession AS mirna_accession,
               mi.primary_name AS mirna_name, mi.reference_level, mi.organism,
               te.id AS term_entity_id, te.accession AS term_accession,
               te.primary_name AS term_name, te.organism AS term_organism
        FROM association a
        JOIN entity mi ON mi.id = a.mirna_entity_id
        JOIN entity te ON te.id = a.term_entity_id
        WHERE a.id = ?
    """, (association_id,))


def association_ranks(con, association: dict) -> dict:
    """Where an association stands by evidence among its neighbours.

    Local rather than global on purpose: about half of all associations of every
    type rest on a single article, so a percentile over all of them puts anything
    with a handful of articles in the top few percent.

    Within the term, only miRNAs of the same reference level are compared, so a
    precursor is not ranked against families that pool several precursors.
    """
    score = association["score"]
    in_mirna = con.execute("""
        SELECT count(*), ifnull(sum(score > :s), 0) FROM association
        WHERE mirna_entity_id = :m AND term_type = :tt
    """, {"s": score, "m": association["mirna_entity_id"], "tt": association["term_type"]}).fetchone()
    in_term = con.execute("""
        SELECT count(*), ifnull(sum(a.score > :s), 0)
        FROM association a JOIN entity m ON m.id = a.mirna_entity_id
        WHERE a.term_entity_id = :t AND m.reference_level IS :lvl
    """, {"s": score, "t": association["term_entity_id"], "lvl": association["reference_level"]}).fetchone()
    return {
        "in_mirna": {"rank": in_mirna[1] + 1, "total": in_mirna[0]},
        "in_term": {"rank": in_term[1] + 1, "total": in_term[0]},
    }


def association_labels(con, association_id: int) -> dict:
    """Label breakdown of an association's direct evidence: the labels that state a
    relation, in display order, and 'none' apart."""
    by_label = {row["label"]: row for row in _rows(con, """
        SELECT label, n_articles, n_sentences FROM association_label WHERE association_id = ?
    """, (association_id,))}
    return {"relations": [by_label[label] for label in LABELS if label in by_label],
            "none": by_label.get("none")}


def association_subterms(con, association: dict) -> list[dict]:
    """The miRNA's associations with the descendants of the term that have direct
    evidence, most direct articles first. A propagated association has no evidence
    of its own; these hold it. Empty for terms without an ontology (genes) and for
    roots, whose IC of 0 receives no propagated evidence (analysis.py)."""
    if not association["ic"]:
        return []
    return _rows(con, """
        SELECT a.id, te.accession AS term_accession, te.primary_name AS term_name, a.n_direct_articles
        FROM ontology_closure oc
        JOIN association a ON a.mirna_entity_id = :m AND a.term_entity_id = oc.descendant_id
        JOIN entity te     ON te.id = a.term_entity_id
        WHERE oc.ancestor_id = :t AND a.n_direct_articles > 0
        ORDER BY a.n_direct_articles DESC, te.primary_name
    """, {"m": association["mirna_entity_id"], "t": association["term_entity_id"]})


def evidence_labels(con, association_ids: list[int]) -> list[str]:
    """The labels of the sentences of these associations, in display order, 'none' last."""
    present = {row[0] for row in con.execute(
        "SELECT DISTINCT label FROM association_label WHERE association_id IN (SELECT value FROM json_each(?))",
        (json.dumps(association_ids),))}
    return [label for label in (*LABELS, "none") if label in present]


def association_evidence(con, association_id: int, page: int = 1, per_page: int = EVIDENCE_PER_PAGE,
                         label: str | None = None, sort: str = "article", subterms: list[dict] = ()) -> dict:
    """Evidence sentences, paginated by SENTENCE rather than by evidence row.

    A sentence can carry several (miRNA span, term span) pairs -- the largest
    association has 23,810 evidence rows over 16,228 distinct sentences -- so
    paginating by row would show the same sentence repeatedly.

    With a label, only the sentences with at least one pair of that label. A card
    still shows every pair and label of its sentence.

    With subterms (association_subterms), also the sentences of those associations;
    a card then lists the subterms its pairs come from under `via`.
    """
    assert sort in EVIDENCE_SORTS, sort
    via = {s["id"]: s for s in subterms}

    def pairs(joined: bool) -> str:
        # mention_pair only when a label or the confidence order needs it: without it
        # ix_ae_assoc covers the count and the article order (notes/DATABASE_EVALUATION.md, finding 5)
        return f"""
            FROM association_evidence ae {"JOIN mention_pair mp ON mp.id = ae.mention_pair_id" if joined else ""}
            WHERE ae.association_id IN (SELECT value FROM json_each(:ids)) {"AND mp.label = :label" if label else ""}
        """
    params = {"ids": json.dumps([association_id, *via]), "label": label,
              "lim": per_page, "off": (page - 1) * per_page}
    total = con.execute("SELECT count(DISTINCT ae.sentence_id)" + pairs(bool(label)), params).fetchone()[0]

    if sort == "article":
        # sentence ids are assigned in corpus order; ix_ae_assoc provides them sorted for one association
        order = "ae.sentence_id"
    elif label:
        order = "max(mp.confidence) DESC, ae.sentence_id"
    else:
        # by the most confident stated relation; sentences with only 'none' come last
        order = "max(CASE WHEN mp.label != 'none' THEN mp.confidence END) DESC, ae.sentence_id"
    sentence_ids = [row[0] for row in con.execute(
        f"SELECT ae.sentence_id {pairs(bool(label) or sort == 'confidence')} "
        f"GROUP BY ae.sentence_id ORDER BY {order} LIMIT :lim OFFSET :off",
        params)]

    rows = _rows(con, f"""
        SELECT ae.association_id, ae.sentence_id, s.sentence_text, s.section_num,
               ar.external_id, ar.year, ar.journal,
               ae.mirna_start, ae.mirna_end, ae.term_start, ae.term_end,
               mp.label, mp.confidence
        FROM association_evidence ae
        JOIN mention_pair mp ON mp.id = ae.mention_pair_id
        JOIN sentence s ON s.id = ae.sentence_id
        JOIN article ar ON ar.id = s.article_id
        WHERE ae.association_id IN (SELECT value FROM json_each(?))
          AND ae.sentence_id IN ({",".join("?" * len(sentence_ids))})
    """, [params["ids"], *sentence_ids])

    grouped: dict[int, dict] = {}
    for row in rows:
        card = grouped.setdefault(row["sentence_id"], {
            "sentence_id": row["sentence_id"],
            "text": row["sentence_text"],
            "section_num": row["section_num"],
            "external_id": row["external_id"],
            "year": row["year"],
            "journal": row["journal"],
            "spans": [],
            "confidences": {},
            "via": {},
        })
        text = row["sentence_text"]
        card["spans"].append(extend_mirna_span(text, row["mirna_start"], row["mirna_end"]) + ("mir",))
        card["spans"].append((row["term_start"], row["term_end"], "term"))
        if row["association_id"] in via:
            card["via"][row["association_id"]] = via[row["association_id"]]
        if row["label"]:     # NULL for a pair the model could not label
            best = card["confidences"].get(row["label"], 0)
            card["confidences"][row["label"]] = max(best, row["confidence"])

    items = [grouped[sentence_id] for sentence_id in sentence_ids]
    for card in items:
        card["html"] = render(card["text"], card["spans"])
        card["via"] = list(card["via"].values())
        # one entry per distinct label of the sentence's pairs, most confident first
        card["labels"] = [
            {"label": pair_label, "confidence": confidence, "level": confidence_level(confidence)}
            for pair_label, confidence in sorted(card["confidences"].items(), key=lambda kv: -kv[1])
        ]
    return {"items": items, "total": total, "page": page, "per_page": per_page}


def year_articles(con, mir_key: str, year: int, limit: int = 200) -> list[dict]:
    """The articles behind one bar of a miRNA timeline."""
    return _rows(con, """
        SELECT ar.external_id, ar.year, ar.journal
        FROM mir_mention_article m
        JOIN article ar ON ar.id = m.article_id
        WHERE m.mir_key = ? AND ar.year = ?
        ORDER BY ar.external_id LIMIT ?
    """, (mir_key, year, limit))


# ---------------------------------------------------------------- ID conflicts

def name_conflict(con: sqlite3.Connection, name: str) -> dict | None:
    """The miRBase release history of an ambiguous identifier.

    Deliberately resolves nothing. Publication year dates the paper, not the
    miRBase release its authors were working from -- lab pipelines lag releases
    and reviews inherit legacy names from their sources -- so assigning a
    mention to one accession by date would be a guess with no bound on its error.
    """
    key = name.strip().lower()
    candidates = _rows(con, """
        SELECT h.accession, h.reference_level,
               min(h.version_rank) AS first_rank, max(h.version_rank) AS last_rank,
               count(*) AS n_versions,
               e.primary_name AS current_name, e.obsolete, e.id AS entity_id
        FROM mirna_name_history h
        LEFT JOIN entity e ON e.accession = h.accession
        WHERE lower(h.mirna_name) = ?
        GROUP BY h.accession, h.reference_level
        ORDER BY h.reference_level, min(h.version_rank)
    """, (key,))
    if not candidates:
        return None

    for candidate in candidates:
        versions = _rows(con, """
            SELECT version FROM mirna_name_history
            WHERE lower(mirna_name) = ? AND accession = ?
            ORDER BY version_rank
        """, (key, candidate["accession"]))
        candidate["first_version"] = versions[0]["version"]
        candidate["last_version"] = versions[-1]["version"]

    by_level: dict[str, set] = {}
    for candidate in candidates:
        by_level.setdefault(candidate["reference_level"], set()).add(candidate["accession"])
    ambiguous = any(len(accessions) > 1 for accessions in by_level.values())

    return {
        "name": name,
        "ambiguous": ambiguous,
        "candidates": candidates,
        "timeline": mirna_timeline(con, key),
    }


def conflicts_for_accession(con: sqlite3.Connection, accession: str) -> list[str]:
    """Ambiguous names this accession has carried, so a miRNA page can link out."""
    return [
        row["mirna_name"] for row in _rows(con, """
            SELECT DISTINCT h.mirna_name
            FROM mirna_name_history h
            WHERE h.accession = ?
              AND EXISTS (
                  SELECT 1 FROM mirna_name_history o
                  WHERE lower(o.mirna_name) = lower(h.mirna_name)
                    AND o.reference_level = h.reference_level
                    AND o.accession <> h.accession
              )
        """, (accession,))
    ]


# The organism menu is an aggregate over all 1.3M associations -- 0.32s, and it
# was being recomputed on every page load. The database is opened immutable, so
# the answer cannot change while the process runs.
_ORGANISM_CACHE: list[dict] | None = None


def organisms(con: sqlite3.Connection, limit: int = 30) -> list[dict]:
    """Organisms that actually have associations, for the filter menu."""
    global _ORGANISM_CACHE
    if _ORGANISM_CACHE is None:
        _ORGANISM_CACHE = _rows(con, """
            SELECT m.organism, count(*) AS n
            FROM association a JOIN entity m ON m.id = a.mirna_entity_id
            WHERE m.organism IS NOT NULL
            GROUP BY m.organism ORDER BY n DESC LIMIT ?
        """, (limit,))
    return _ORGANISM_CACHE


_LANDING_CACHE: dict | None = None


def landing_stats(con: sqlite3.Connection) -> dict:
    """Database contents for the landing page. Scans every association, so it is
    cached like the organism menu."""
    global _LANDING_CACHE
    if _LANDING_CACHE is None:
        by_type, by_label, total = {}, {}, 0
        for term_type, label, direct, n in con.execute("""
            SELECT term_type, dominant_label, n_direct_articles > 0, count(*) FROM association GROUP BY 1, 2, 3
        """):
            counts = by_type.setdefault(term_type, {"direct": 0, "propagated": 0})
            counts["direct" if direct else "propagated"] += n
            if label:
                by_label[label] = by_label.get(label, 0) + n
            total += n
        n_mirnas, n_terms = con.execute(
            "SELECT count(DISTINCT mirna_entity_id), count(DISTINCT term_entity_id) FROM association").fetchone()
        n_articles, n_undated = con.execute("SELECT count(*), sum(year IS NULL) FROM article").fetchone()
        n_early = con.execute("SELECT ifnull(sum(n_articles), 0) FROM corpus_year WHERE year < ?",
                              (CORPUS_TIMELINE_START,)).fetchone()[0]
        _LANDING_CACHE = {
            "n_mirnas": n_mirnas, "n_terms": n_terms, "n_associations": total,
            "n_articles": n_articles, "n_undated": n_undated, "n_early": n_early,
            "types": sorted(({"type": t, **c} for t, c in by_type.items()),
                            key=lambda r: r["direct"] + r["propagated"], reverse=True),
            "labels": sorted(({"label": l, "n": n} for l, n in by_label.items()), key=lambda r: r["n"], reverse=True),
            "n_no_label": total - sum(by_label.values()),
        }
    return _LANDING_CACHE


def corpus_timeline(con: sqlite3.Connection) -> list[dict]:
    """Articles per year in the corpus, for the landing page."""
    return _rows(con, "SELECT year, n_articles FROM corpus_year WHERE year >= ? ORDER BY year",
                 (CORPUS_TIMELINE_START,))


_LABELS_CACHE: dict[str, list[str]] | None = None


def labels_by_type(con: sqlite3.Connection) -> dict[str, list[str]]:
    """The dominant labels that occur per term type, for the filter menu
    ('targets' exists for genes only). Cached like the organism menu."""
    global _LABELS_CACHE
    if _LABELS_CACHE is None:
        found = {(row[0], row[1]) for row in con.execute(
            "SELECT DISTINCT term_type, dominant_label FROM association WHERE dominant_label IS NOT NULL")}
        _LABELS_CACHE = {t: [label for label in LABELS if (t, label) in found] for t in TERM_TYPES}
    return _LABELS_CACHE
