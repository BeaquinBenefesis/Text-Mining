"""Read-only queries backing the UI. One function per panel; each takes an open
connection and returns plain dicts.

No ORM, matching the raw-SQL decision in DATABASE_DESIGN_NOTES.txt section 8.1.
"""
import sqlite3
from dataclasses import dataclass
from math import log2

from textmining.web.highlight import extend_mirna_span, render

PER_PAGE = 25
EVIDENCE_PER_PAGE = 20

TERM_TYPES = ("DISEASE", "BIOLOGICAL_PROCESS", "CELL", "PATHWAY", "TISSUE")


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
               reference_level, organism
        FROM entity WHERE accession = ?
    """, (accession,))


# ---------------------------------------------------------------- timelines

def _normalise(rows: list[dict]) -> list[dict]:
    """Attach share-of-corpus alongside the raw count.

    The corpus is 99% post-2010 and 46% post-2020, so a raw per-year count is
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


def association_timeline(con: sqlite3.Connection, association_id: int) -> list[dict]:
    return _normalise(_rows(con, """
        SELECT a.year, count(DISTINCT s.article_id) AS n_articles,
               cy.n_articles AS corpus_articles
        FROM association_evidence ae
        JOIN sentence s     ON s.id = ae.sentence_id
        JOIN article a      ON a.id = s.article_id
        JOIN corpus_year cy ON cy.year = a.year
        WHERE ae.association_id = ?
        GROUP BY a.year ORDER BY a.year
    """, (association_id,)))


# ---------------------------------------------------------------- research score

@dataclass
class ResearchScore:
    score: float
    weighted_volume: float
    breadth: int
    n_articles: int


# Both terms are log-compressed, matching the saturation AssociationEvidence
# already applies per article (models.py). w1/w2 are NOT settled -- they need
# validating against an external measure of study depth (HMDD entry count per
# miRNA is the natural choice and is already the planned benchmark).
SCORE_W_VOLUME = 1.0
SCORE_W_BREADTH = 1.0


def research_score(con: sqlite3.Connection, entity_id: int, mir_key: str) -> ResearchScore:
    """How much attention a miRNA has received.

    Volume runs on share-of-corpus rather than raw article counts, so a miRNA is
    not rewarded merely for having been studied in the years the corpus covers
    best. A recency term is deliberately absent for the same reason: the corpus
    is already recency-biased, and adding one would double-count that artefact.

    This measures attention, not how well characterised a miRNA is; it will be
    topped by miR-21, miR-155 and let-7.
    """
    timeline = mirna_timeline(con, mir_key)
    weighted_volume = sum(row["share"] for row in timeline)
    n_articles = sum(row["n_articles"] for row in timeline)
    breadth = con.execute(
        "SELECT count(DISTINCT term_entity_id) FROM association WHERE mirna_entity_id = ?",
        (entity_id,),
    ).fetchone()[0]
    score = (SCORE_W_VOLUME * log2(1 + weighted_volume)
             + SCORE_W_BREADTH * log2(1 + breadth))
    return ResearchScore(score, weighted_volume, breadth, n_articles)


# ---------------------------------------------------------------- associations

def mirna_association_counts(con: sqlite3.Connection, entity_id: int) -> dict[str, int]:
    return {
        row["term_type"]: row["n"]
        for row in _rows(con, """
            SELECT term_type, count(*) AS n FROM association
            WHERE mirna_entity_id = ? GROUP BY term_type
        """, (entity_id,))
    }


def mirna_associations(con, entity_id: int, term_type: str | None = None,
                       page: int = 1, per_page: int = PER_PAGE) -> dict:
    where = "a.mirna_entity_id = :eid"
    params = {"eid": entity_id, "lim": per_page, "off": (page - 1) * per_page}
    if term_type:
        where += " AND a.term_type = :tt"
        params["tt"] = term_type
    total = con.execute(
        f"SELECT count(*) FROM association a WHERE {where}",
        {k: v for k, v in params.items() if k in ("eid", "tt")},
    ).fetchone()[0]
    items = _rows(con, f"""
        SELECT a.id, a.score, a.term_type,
               e.accession AS term_accession, e.primary_name AS term_name
        FROM association a
        JOIN entity e ON e.id = a.term_entity_id
        WHERE {where}
        ORDER BY a.score DESC LIMIT :lim OFFSET :off
    """, params)
    return {"items": items, "total": total, "page": page, "per_page": per_page}


def term_mirnas(con, term_entity_id: int, expand: bool = True,
                organism: str | None = "hsa", page: int = 1,
                per_page: int = PER_PAGE) -> dict:
    """miRNAs associated with a term, optionally including its ontology descendants.

    Scores are aggregated with MAX, never summed. Association scores are already
    log-compressed per term, so adding a miRNA's carcinoma-subtype scores together
    would inflate broad terms in proportion to how many subtypes happen to
    co-occur -- the failure mode set out in design notes section 5.2. This is
    query expansion (section 5.1a), not the precomputed evidence propagation of
    5.1b, which does not exist yet.

    ontology_closure holds strict ancestry only -- `ancestors()` excludes self --
    so the term itself must be unioned in or its own associations disappear.

    Two passes rather than one: the per-miRNA term counts and names are gathered
    for the page's 25 miRNAs only. Computing them as correlated subqueries over
    the expanded set instead cost ~2s on the MONDO root, which expands to every
    disease in the ontology.
    """
    targets = "SELECT :tid AS id" + (
        " UNION SELECT descendant_id FROM ontology_closure WHERE ancestor_id = :tid"
        if expand else ""
    )
    org_filter = "AND m.organism = :org" if organism else ""
    params = {"tid": term_entity_id, "org": organism,
              "lim": per_page, "off": (page - 1) * per_page}

    # MATERIALIZED so the expansion is evaluated once, not per reference.
    base = f"""
        WITH targets(id) AS MATERIALIZED ({targets}),
        hits AS MATERIALIZED (
            SELECT a.id, a.score, a.mirna_entity_id
            FROM association a
            JOIN targets t ON t.id = a.term_entity_id
            JOIN entity  m ON m.id = a.mirna_entity_id
            WHERE 1=1 {org_filter}
        )
    """
    total = con.execute(
        base + "SELECT count(DISTINCT mirna_entity_id) FROM hits", params
    ).fetchone()[0]

    items = _rows(con, base + """
        , ranked AS (
            SELECT h.id, h.score, h.mirna_entity_id,
                   row_number() OVER (
                       PARTITION BY h.mirna_entity_id ORDER BY h.score DESC, h.id
                   ) AS rn
            FROM hits h
        )
        SELECT r.id, r.score,
               m.accession AS mirna_accession, m.primary_name AS mirna_name,
               m.reference_level, m.organism, m.id AS mirna_entity_id
        FROM ranked r
        JOIN entity m ON m.id = r.mirna_entity_id
        WHERE r.rn = 1
        ORDER BY r.score DESC LIMIT :lim OFFSET :off
    """, params)

    _attach_matched_terms(con, items, term_entity_id, expand)
    return {"items": items, "total": total, "page": page, "per_page": per_page}


def _attach_matched_terms(con, items: list[dict], term_entity_id: int,
                          expand: bool, show: int = 4) -> None:
    """Which terms each listed miRNA actually matched through -- the answer to
    'why is this miRNA here?' when the query was expanded over the ontology."""
    if not items:
        return
    ids = [row["mirna_entity_id"] for row in items]
    placeholders = ",".join("?" * len(ids))
    descendant_clause = (
        "OR a.term_entity_id IN (SELECT descendant_id FROM ontology_closure WHERE ancestor_id = ?)"
        if expand else ""
    )
    params = ids + [term_entity_id] + ([term_entity_id] if expand else [])
    matched: dict[int, list[str]] = {}
    for row in con.execute(f"""
        SELECT a.mirna_entity_id, te.primary_name, a.score
        FROM association a
        JOIN entity te ON te.id = a.term_entity_id
        WHERE a.mirna_entity_id IN ({placeholders})
          AND (a.term_entity_id = ? {descendant_clause})
        ORDER BY a.score DESC
    """, params):
        matched.setdefault(row[0], []).append(row[1])

    for row in items:
        names = matched.get(row["mirna_entity_id"], [])
        row["n_terms"] = len(names)
        row["via_terms"] = " | ".join(sorted(names[:show]))


def get_association(con: sqlite3.Connection, association_id: int) -> dict | None:
    return _one(con, """
        SELECT a.id, a.score, a.term_type,
               mi.id AS mirna_entity_id, mi.accession AS mirna_accession,
               mi.primary_name AS mirna_name, mi.reference_level, mi.organism,
               te.id AS term_entity_id, te.accession AS term_accession,
               te.primary_name AS term_name
        FROM association a
        JOIN entity mi ON mi.id = a.mirna_entity_id
        JOIN entity te ON te.id = a.term_entity_id
        WHERE a.id = ?
    """, (association_id,))


def association_evidence(con, association_id: int, page: int = 1,
                         per_page: int = EVIDENCE_PER_PAGE) -> dict:
    """Evidence sentences, paginated by SENTENCE rather than by evidence row.

    A sentence can carry several (miRNA span, term span) pairs -- the largest
    association has 23,810 evidence rows over 16,228 distinct sentences -- so
    paginating by row would show the same sentence repeatedly.
    """
    total = con.execute(
        "SELECT count(DISTINCT sentence_id) FROM association_evidence WHERE association_id = ?",
        (association_id,),
    ).fetchone()[0]

    rows = _rows(con, """
        WITH page AS (
            -- ordered by sentence_id, which ix_ae_assoc(association_id, sentence_id)
            -- already provides: DISTINCT and ORDER BY are then a range scan over the
            -- page rather than a group-and-sort over every row of the association.
            -- Sentence ids are assigned in corpus order, so this is article order.
            SELECT DISTINCT ae.sentence_id
            FROM association_evidence ae
            WHERE ae.association_id = :aid
            ORDER BY ae.sentence_id LIMIT :lim OFFSET :off
        )
        SELECT p.sentence_id, s.sentence_text, s.section_num,
               ar.external_id, ar.year, ar.journal,
               ae.mirna_start, ae.mirna_end, ae.term_start, ae.term_end
        FROM page p
        JOIN association_evidence ae
             ON ae.sentence_id = p.sentence_id AND ae.association_id = :aid
        JOIN sentence s ON s.id = p.sentence_id
        JOIN article ar ON ar.id = s.article_id
        ORDER BY p.sentence_id
    """, {"aid": association_id, "lim": per_page, "off": (page - 1) * per_page})

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
        })
        text = row["sentence_text"]
        card["spans"].append(extend_mirna_span(text, row["mirna_start"], row["mirna_end"]) + ("mir",))
        card["spans"].append((row["term_start"], row["term_end"], "term"))

    items = list(grouped.values())
    for card in items:
        card["html"] = render(card["text"], card["spans"])
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
