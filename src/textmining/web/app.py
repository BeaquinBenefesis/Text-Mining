"""FastAPI application serving the miRNA knowledgebase.

Server-rendered Jinja: every view is a real URL with its filters and page number
as query parameters, so pages are bookmarkable and debuggable with curl. The only
client-side code is the timeline charts.
"""
import logging
import sqlite3
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from textmining.db.connect import DB_PATH, open_readonly
from textmining.web import queries as q

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
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
        con = _local.con = open_readonly(DB_PATH, immutable=True, check_same_thread=False)
    return con


def _page(request: Request, name: str, **context) -> HTMLResponse:
    return templates.TemplateResponse(request, name, context)


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
    page: int = Query(1, ge=1),
):
    con = db()
    entity = q.get_entity(con, accession)
    if entity is None or entity["entity_type"] != "MIR":
        raise HTTPException(404, f"No miRNA with accession {accession}")
    return _page(
        request, "mirna.html",
        entity=entity,
        score=q.research_score(con, entity["id"], accession),
        counts=q.mirna_association_counts(con, entity["id"]),
        associations=q.mirna_associations(con, entity["id"], type, page),
        conflicts=q.conflicts_for_accession(con, accession),
        term_types=q.TERM_TYPES,
        selected_type=type,
    )


@app.get("/term/{accession}", response_class=HTMLResponse)
def term_view(
    request: Request,
    accession: str,
    organism: str | None = Query("hsa", description="miRBase organism prefix; blank for all"),
    expand: bool = Query(True, description="Include ontology descendants of this term"),
    page: int = Query(1, ge=1),
):
    con = db()
    entity = q.get_entity(con, accession)
    if entity is None or entity["entity_type"] == "MIR":
        raise HTTPException(404, f"No ontology term with accession {accession}")
    return _page(
        request, "term.html",
        entity=entity,
        results=q.term_mirnas(con, entity["id"], expand, organism or None, page),
        organisms=q.organisms(con),
        organism=organism, expand=expand,
    )


@app.get("/association/{association_id}", response_class=HTMLResponse)
def association_view(request: Request, association_id: int, page: int = Query(1, ge=1)):
    con = db()
    association = q.get_association(con, association_id)
    if association is None:
        raise HTTPException(404, f"No association {association_id}")
    return _page(
        request, "association.html",
        association=association,
        evidence=q.association_evidence(con, association_id, page),
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


# ------------------------------------------------------- JSON (charts + API)

@app.get("/api/mirna/{mir_key}/timeline")
def api_mirna_timeline(mir_key: str):
    """Articles per year mentioning a miRNA, with its share of that year's corpus.

    `mir_key` is a miRBase accession, or a surface name for an ambiguous
    identifier that normalises to no accession.
    """
    return {"mir_key": mir_key, "points": q.mirna_timeline(db(), mir_key)}


@app.get("/api/association/{association_id}/timeline")
def api_association_timeline(association_id: int):
    """Articles per year supporting one association, with its corpus share."""
    return {"association_id": association_id,
            "points": q.association_timeline(db(), association_id)}
