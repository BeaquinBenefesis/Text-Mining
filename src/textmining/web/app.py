"""FastAPI application serving the miRNA knowledgebase.

Server-rendered Jinja: every view is a real URL with its filters and page number
as query parameters, so pages are bookmarkable and debuggable with curl. The only
client-side code is the timeline charts.
"""
import logging
import os
import sqlite3
import threading
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from textmining.db.connect import DB_PATH, open_readonly
from textmining.web import queries as q

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
# TEXTMINING_DB points the UI at another build, e.g. the migrated dev copy.
DB = Path(os.environ.get("TEXTMINING_DB", DB_PATH))
# written by build_db next to the database
DOWNLOADS = DB.parent / "downloads"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="miRNA knowledgebase", docs_url="/docs")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# One connection per thread: FastAPI runs sync endpoints in a threadpool and a
# sqlite3 connection may not be shared across threads. The database is opened
# immutable, so these are pure readers and never contend.
_local = threading.local()


def db() -> sqlite3.Connection:
    con = getattr(_local, "con", None)
    if con is None:
        con = _local.con = open_readonly(DB, immutable=True, check_same_thread=False)
    return con


def _static_version() -> int:
    """Newest mtime under static/, appended to asset URLs so that browsers do not
    keep serving a cached stylesheet or script after an edit."""
    return int(max(f.stat().st_mtime for f in (BASE_DIR / "static").iterdir()))


def _page(request: Request, name: str, **context) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {**context, "v": _static_version()})


def _sort(value: str | None, term_type: str | None = None) -> str:
    """Whitelist the sort parameter; anything unknown falls back to the default.
    Types without IC have no relevance and are always ordered by evidence."""
    if term_type in q.UNRANKED_TYPES:
        return "evidence"
    return value if value in q.SORTS else q.SORTS[0]


def _label(value: str | None, term_type: str) -> str | None:
    """Whitelist the label filter against the labels that occur for the term type."""
    return value if value in q.labels_by_type(db())[term_type] else None


@app.on_event("startup")
def prepare_landing_stats():
    # a full scan of the associations: done once in the background, not on the first visit
    threading.Thread(target=lambda: q.landing_stats(db()), daemon=True).start()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return _page(request, "home.html", results=None, query="")


@app.get("/search", response_class=HTMLResponse)
def search_view(request: Request, q_: str = Query("", alias="q")):
    return _page(request, "home.html", results=q.search(db(), q_), query=q_)


@app.get("/mirna/{accession}", response_class=HTMLResponse)
def mirna_view(
    request: Request,
    accession: str,
    type: str | None = Query(None, description="Filter associations by term type"),
    sort: str | None = Query(None, description="relevance (default) or evidence"),
    label: str | None = Query(None, description="Filter associations by dominant relation label"),
    page: int = Query(1, ge=1),
):
    con = db()
    entity = q.get_entity(con, accession)
    if entity is None or entity["entity_type"] != "MIR":
        raise HTTPException(404, f"No miRNA with accession {accession}")
    counts = q.mirna_association_counts(con, entity["id"])
    if type not in q.TERM_TYPES:
        # the default type, unless this miRNA has associations only of other types
        type = next((t for t in (q.DEFAULT_TYPE, *q.TERM_TYPES) if counts.get(t)), q.DEFAULT_TYPE)
    sort = _sort(sort, type)
    label = _label(label, type)
    return _page(
        request, "mirna.html",
        entity=entity,
        stats=q.mirna_stats(con, entity["id"], accession),
        counts=counts,
        associations=q.mirna_associations(con, entity["id"], type, page, sort=sort, label=label),
        labels=q.labels_by_type(con)[type], label=label,
        clouds=q.mirna_term_clouds(con, entity["id"]),
        level_plurals=q.LEVEL_PLURALS,
        conflicts=q.conflicts_for_accession(con, accession),
        term_types=q.TERM_TYPES,
        selected_type=type,
        ranked=type not in q.UNRANKED_TYPES,
        sort=sort,
    )


# :path because some gene ids contain '/' ('Adipoq<i>m1Mcwi</i>@RGD')
@app.get("/term/{accession:path}", response_class=HTMLResponse)
def term_view(
    request: Request,
    accession: str,
    organism: str | None = Query("hsa", description="miRBase organism prefix; blank for all"),
    label: str | None = Query(None, description="Filter associations by dominant relation label"),
    page: int = Query(1, ge=1),
):
    con = db()
    entity = q.get_entity(con, accession)
    if entity is None or entity["entity_type"] == "MIR":
        raise HTTPException(404, f"No term with accession {accession}")
    label = _label(label, entity["entity_type"])
    return _page(
        request, "term.html",
        entity=entity,
        results=q.term_mirnas(con, entity["id"], organism or None, page, label=label),
        labels=q.labels_by_type(con)[entity["entity_type"]], label=label,
        organisms=q.organisms(con),
        organism=organism, ranked=entity["entity_type"] not in q.UNRANKED_TYPES,
    )


@app.get("/associations", response_class=HTMLResponse)
def associations_view(
    request: Request,
    sort: str | None = Query(None, description="relevance (default) or evidence"),
    type: str | None = Query(None, description="Term type (default DISEASE)"),
    organism: str | None = Query("hsa", description="miRBase organism prefix; blank for all"),
    level: str | None = Query("mature", description="mature, precursor or family; blank for all"),
    label: str | None = Query(None, description="Filter associations by dominant relation label"),
    page: int = Query(1, ge=1),
):
    con = db()
    type = type if type in q.TERM_TYPES else q.DEFAULT_TYPE
    sort = _sort(sort, type)
    level = level if level in q.LEVELS else None
    label = _label(label, type)
    return _page(
        request, "associations.html",
        results=q.top_associations(con, sort, type, organism or None, level, page, label=label),
        labels=q.labels_by_type(con)[type], label=label,
        organisms=q.organisms(con),
        term_types=q.TERM_TYPES, levels=q.LEVELS,
        sort=sort, selected_type=type, organism=organism or "", level=level or "",
        ranked=type not in q.UNRANKED_TYPES,
    )


def _evidence_selection(association: dict, subterms: list[dict], via: str | None):
    """(via, association id, subterms) of the evidence shown: the sentences of the term and
    of all its subterms by default; via narrows them to one of these terms."""
    terms = {association["term_accession"]: association["id"], **{s["term_accession"]: s["id"] for s in subterms}}
    via = via if via in terms else None
    return (via, terms[via], []) if via else (None, association["id"], subterms)


@app.get("/association/{association_id}", response_class=HTMLResponse)
def association_view(
    request: Request,
    association_id: int,
    label: str | None = Query(None, description="Show only sentences with this relation label"),
    sort: str | None = Query(None, description="article (default) or confidence"),
    via: str | None = Query(None, description="Show only the sentences of this term or one of its subterms"),
    page: int = Query(1, ge=1),
):
    con = db()
    association = q.get_association(con, association_id)
    if association is None:
        raise HTTPException(404, f"No association {association_id}")
    breakdown = q.association_labels(con, association_id)
    subterms = q.association_subterms(con, association)
    via, evidence_id, evidence_subterms = _evidence_selection(association, subterms, via)
    # the sentence filter offers the labels of the sentences shown, 'none' included
    labels = q.evidence_labels(con, [evidence_id, *(s["id"] for s in evidence_subterms)])
    label = label if label in labels else None
    sort = sort if sort in q.EVIDENCE_SORTS else q.EVIDENCE_SORTS[0]
    return _page(
        request, "association.html",
        association=association,
        ranked=association["term_type"] not in q.UNRANKED_TYPES,
        type_plurals=q.TYPE_PLURALS, level_plurals=q.LEVEL_PLURALS,
        breakdown=breakdown, labels=labels, label=label, sort=sort,
        subterms=subterms, via=via,
        evidence=q.association_evidence(con, evidence_id, page, label=label, sort=sort,
                                        subterms=evidence_subterms),
    )


@app.get("/name/{name}", response_class=HTMLResponse)
def name_view(request: Request, name: str):
    conflict = q.name_conflict(db(), name)
    if conflict is None:
        raise HTTPException(404, f"No miRBase history for {name}")
    return _page(request, "conflict.html", conflict=conflict)


@app.get("/mirna/{accession}/year/{year}", response_class=HTMLResponse)
def year_view(request: Request, accession: str, year: int):
    con = db()
    entity = q.get_entity(con, accession)
    return _page(
        request, "year.html",
        accession=accession, year=year, entity=entity,
        articles=q.year_articles(con, accession, year),
    )


@app.get("/downloads", response_class=HTMLResponse)
def downloads_view(request: Request):
    files = sorted(DOWNLOADS.glob("*.tsv.gz")) if DOWNLOADS.is_dir() else []
    return _page(request, "downloads.html", files=[(f.name, f.stat().st_size) for f in files])


@app.get("/downloads/{name}")
def download_file(name: str):
    path = DOWNLOADS / name
    # only the listed files, never a path outside the directory
    if path.parent != DOWNLOADS or not name.endswith(".tsv.gz") or not path.is_file():
        raise HTTPException(404, f"No download {name}")
    return FileResponse(path, media_type="application/gzip", filename=name)


# ------------------------------------------------------- JSON (charts + API)

@app.get("/api/mirna/{mir_key}/timeline")
def api_mirna_timeline(mir_key: str):
    """Articles per year mentioning a miRNA, with its share of that year's corpus.

    `mir_key` is a miRBase accession, or a surface name for an ambiguous
    identifier that normalises to no accession.
    """
    return {"mir_key": mir_key, "points": q.mirna_timeline(db(), mir_key)}


@app.get("/api/association/{association_id}/timeline")
def api_association_timeline(association_id: int, via: str | None = Query(None)):
    """Articles per year supporting one association and its subterms, with its corpus share;
    via selects the evidence as on the association page."""
    con = db()
    association = q.get_association(con, association_id)
    if association is None:
        raise HTTPException(404, f"No association {association_id}")
    _, evidence_id, evidence_subterms = _evidence_selection(association, q.association_subterms(con, association), via)
    return {"association_id": association_id,
            "points": q.association_timeline(con, [evidence_id, *(s["id"] for s in evidence_subterms)])}


@app.get("/api/suggest")
def api_suggest(q_: str = Query("", alias="q"), limit: int = Query(8, ge=1, le=30)):
    """Search suggestions: the first matches of the search, from two characters on."""
    if len(q_.strip()) < 2:
        return []
    suggestions = []
    for r in q.search(db(), q_, limit=limit):
        if r["kind"] == "conflict":
            suggestions.append({"name": r["display_name"], "url": f"/name/{quote(r['display_name'])}",
                                "meta": "ambiguous identifier", "matched": None})
            continue
        prefix = "/mirna/" if r["entity_type"] == "MIR" else "/term/"
        entity_type = "miRNA" if r["entity_type"] == "MIR" else r["entity_type"].lower().replace("_", " ")
        meta = [entity_type, r["reference_level"], r["organism"]]
        matched = r["display_name"] if r["display_name"].lower() != r["primary_name"].lower() else None
        suggestions.append({"name": r["primary_name"], "url": prefix + quote(r["accession"]),
                            "meta": " · ".join(m for m in meta if m), "matched": matched})
    return suggestions


@app.get("/api/stats")
def api_stats():
    """Database contents for the landing page."""
    return q.landing_stats(db())


@app.get("/api/corpus/timeline")
def api_corpus_timeline():
    """Articles per year in the corpus."""
    return {"points": q.corpus_timeline(db())}


@app.get("/api/association/{association_id}/ranks")
def api_association_ranks(association_id: int):
    """Where an association stands by evidence among its neighbours."""
    con = db()
    association = q.get_association(con, association_id)
    if association is None:
        raise HTTPException(404, f"No association {association_id}")
    return q.association_ranks(con, association)
