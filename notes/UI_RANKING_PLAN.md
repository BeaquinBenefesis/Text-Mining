# UI: specificity-weighted ranking (relevance = E · ic²)

Status: implemented 2026-09-17 on the migrated dev database (`db/atlas_dev.db`); `verify_ui.py` passes all
sections. Remaining: verification step 5 (after the rerun's real build). Background and decisions:
`WEIGHTED_RANKING_PLAN.md` §2, `DATABASE_DESIGN_NOTES.txt` §16.6.

## Context

The miRNA and term pages rank associations by raw `association.score`, so every facet's top row is a
vacuous term (*neoplasm*, *disease*, *cell*, *pathway*). The analysis (`analysis/ic_distribution.ipynb`,
`IC_THRESHOLD_ANALYSIS.md` §9) settled on ranking by evidence discounted by normalised structural IC:

- **relevance = E · ic^α, α = 2**, where `E = association.evidence_mass` (evidence before the outer log)
  and `ic = entity.ic`. Displayed as `log2(1 + ic^α · E)`, in the same units as `score`.
  Top-10 check on 1,021 human miRNAs: general terms drop out for 96%, while well-supported specific
  cancers stay (unlike `score × ic`, which removed them).
- Decided: **no minimum-article guard** (all evidence stays), **no "specificity" sort**, and the
  **All tab ranks by relevance too**, with a note that IC is not calibrated across ontologies.
- A full pipeline rerun is in progress and won't produce a database yet. The current `db/atlas.db`
  (2026-09-11) lacks `entity.ic`, `association.evidence_mass`, `n_articles` and `n_direct_articles`, so
  development runs against a **migrated copy**.

Schema, loaders and `.assoc` already have the new columns (`src/textmining/db/schema/core.sql`,
`loaders/entity.py`, `loaders/association.py`, `results_io.py`).

## Step 1: Dev database and DB path override

- **New `scripts/web/make_dev_db.py`** (dev-only; never touches `db/atlas.db`):
  - copies `db/atlas.db` to `db/atlas_dev.db`;
  - adds the columns via `ALTER TABLE`:
    - `entity.ic`: for each ontology in `ONTOLOGY_SOURCES` except TAXON, load
      `OntologyGraph.from_source` and compute `max(0.0, compute_ic_from_index(idx) / log(node_num))`,
      the same expression as `loaders/entity.py`. Stale accessions not in the current graph stay NULL.
    - `association.evidence_mass = pow(2, score) - 1`
    - `association.n_direct_articles` = distinct `sentence.article_id` over `association_evidence`
    - `association.n_articles = max(n_direct_articles, 1)`, a **placeholder** (propagated counts can't
      be rebuilt from the DB). Print a warning saying so.
  - prints NULL-`ic` counts per type, so stale-ID coverage is visible.
- **`src/textmining/web/app.py`:** `DB = Path(os.environ.get("TEXTMINING_DB", DB_PATH))`, used in `db()`.
- **`scripts/web/run_ui.py`:** add `--db PATH`, which sets `TEXTMINING_DB` before `uvicorn.run`
  (inherited by `--reload` workers).
- **`scripts/web/verify_ui.py`:** honour `TEXTMINING_DB` in the same way.

## Step 2: Queries (`src/textmining/web/queries.py`)

- **Module constants:**
  ```python
  RELEVANCE_ALPHA = 2          # E · ic^α; provisional, see WEIGHTED_RANKING_PLAN.md
  SORTS = ("relevance", "evidence")
  ```
  Keep one helper returning the SQL fragments (never interpolate user input):
  `_rank_expr(sort, a, e)`: relevance gives `a.evidence_mass * pow(e.ic, :alpha)`; evidence gives `a.score`.
  Tie-breakers: `a.score DESC, a.id`.
- **`mirna_associations(..., sort="relevance")`:**
  - SELECT adds `a.evidence_mass`, `a.n_articles`, `a.n_direct_articles`, `e.ic`, and
    `log2(1 + a.evidence_mass * pow(e.ic, :alpha)) AS relevance`;
  - `ORDER BY` uses the rank expression; the `total` query is unchanged (no filtering).
- **`term_mirnas(..., sort="relevance")`:**
  - `hits` CTE: `JOIN entity te ON te.id = a.term_entity_id`; carry `a.score`, `a.evidence_mass`, `te.ic`,
    `a.n_articles`, plus a computed `rank_key`;
  - `ranked` window and the final `ORDER BY` use `rank_key DESC, score DESC, id`;
  - return `relevance`, `ic`, `n_articles` for the chosen row.
  - Rewrite the docstring: MAX (not SUM) still holds, but under relevance the maximum is over weighted
    values, so the "best" descendant for a miRNA can change. Remove the outdated line that says
    propagation (5.1b) "does not exist yet".
- **`_attach_matched_terms`:** order matched terms by the same rank key, so "matched via" agrees with the row.
- **`get_association`:** also return `evidence_mass`, `n_articles`, `n_direct_articles`, `te.ic`, and `relevance`.
- `SORTS` validation lives in `app.py` (below); query functions `assert sort in SORTS`.

## Step 3: Routes (`app.py`)

- `mirna_view` and `term_view` accept `sort: str = Query("relevance")`. Anything not in `q.SORTS`
  falls back to `"relevance"`. Pass `sort` to the queries and the templates.

## Step 4: Templates and CSS

- **`mirna.html`:**
  - sort toggle "Relevance | Evidence" next to the facet tabs; tab links and the pager base URL carry
    both `type` and `sort`;
  - columns: Term | Type (All tab only) | **Relevance** | Evidence score | Articles
    (`n_articles`, with `n_direct` in the title attribute or muted "(k direct)") | Specificity (bar);
    the sorted column is marked;
  - on the All tab with relevance sort: a one-line muted note that specificity is not calibrated
    across ontologies, so rankings compare best within one type.
  - one-sentence help under the table: relevance = evidence discounted by specificity (general
    ontology terms rank lower); evidence = amount of literature support.
- **`term.html`:**
  - the same sort toggle, carried by the form (hidden input) and the pager;
  - columns: miRNA | Level | **Best relevance** (or Best score under evidence sort) | Evidence score |
    Articles | Matched via;
  - header: the term's own specificity bar;
  - notice text: update for propagation plus MAX over weighted values.
- **`association.html`:** badges next to score: relevance, specificity (`ic`), and articles
  "n (k direct, n−k via subtypes)".
- **`_pagination.html`:** unchanged; callers build a base URL with all parameters.
- **`style.css`:** `.ic-bar` (small inline bar, width = ic × 100%, muted fill, value in the title
  attribute) and `.sort` toggle styling that reuses `.filters` / `.on`.
- A macro for the bar, shared by the templates (implemented as `_ranking.html`, together with the sort toggle, query strings and help text).

## Step 4b: Example associations page (`/associations`)

A plain listing of all associations under the chosen sort, as a way to browse examples. Nothing is
deduplicated: repeated miR-21/miR-155 rows are expected.

- **Query** `top_associations(con, sort="relevance", term_type=None, organism="hsa", level="mature", page=1)`:
  - joins `association a`, `entity m` (miRNA) and `entity e` (term);
  - optional WHERE on `a.term_type`, `m.organism`, `m.reference_level` (families have no organism, so an
    organism filter excludes them; that's expected);
  - same SELECT columns as `mirna_associations`, plus miRNA name and accession;
  - `ORDER BY` the rank expression from Step 2, `LIMIT/OFFSET` with `PER_PAGE` = 25.
  - **Cost:** a global sort over up to 1.3M rows with no index. Cache `total` and the first pages per
    `(sort, type, organism, level)` in a module dict, like `_ORGANISM_CACHE` (the DB is immutable).
    Measure it in verify_ui; add an index only if the uncached time is unacceptable.
- **Route** `GET /associations` with `sort`, `type` (whitelist `TERM_TYPES`), `organism` (blank = all),
  `level` (`mature|precursor|family`, blank = all) and `page`; invalid values fall back to defaults.
- **Template `associations.html`:**
  - a filter form (sort toggle, type select, organism select from `q.organisms()`, level select);
  - table: miRNA | Term | Type | Relevance | Evidence score | Articles | Specificity bar;
  - rows link to `/association/{id}`, the miRNA page and the term page;
  - the pager carries every parameter; the All-types + relevance note, as on the miRNA page.
- Link "Browse top associations" from `home.html` (and the header nav in `base.html`).

## Step 5: Verification script (`scripts/web/verify_ui.py`)

Add a section **"7. weighted ranking"**:
- `ic` in [0, 1] for non-MIR entities; count NULLs (expected > 0 only on the dev DB, 0 after a real build);
- `evidence_mass ≥ 0`, and `|score − log2(1 + evidence_mass)| < 1e-3`;
- `relevance ≤ score + 1e-9` for every listed row;
- miR-21 DISEASE relevance page: rows non-increasing in `evidence_mass · ic²`; no root term
  (`ic = 0`) above a positive-relevance row;
- `term_mirnas` MAX check (section 4) repeated under relevance sort, against max(E·ic²);
- timings: miR-21 relevance page < 50 ms; `term_mirnas` on the MONDO root, expanded, relevance
  sort < 5 s (report it, and compare with evidence sort);
- `top_associations`: page 1 is ordered by the rank key; uncached timing is reported for
  (relevance, all types, hsa, mature) and (evidence, DISEASE, all, all);
- sort fallback: an invalid `?sort=` returns 200 with the relevance order (via FastAPI `TestClient`,
  if available; otherwise call the view logic directly).

## Step 6: Documentation

- **`WEIGHTED_RANKING_PLAN.md`:**
  - formula becomes `E · ic^α` (α = 2, provisional) with the reason (constant exchange rate vs.
    `score × ic` acting as an exponent; top-10 numbers);
  - record: no min-article guard, specificity sort dropped, All tab ranks by relevance with a note,
    `evidence_mass` column;
  - tick the completed items.
- **`DATABASE_DESIGN_NOTES.txt` §16.5:** short amendment with the same decision.

## Critical files

- `src/textmining/web/queries.py`, `src/textmining/web/app.py`
- `src/textmining/web/templates/{mirna,term,association,home,base}.html`, new `associations.html` and
  `_ranking.html`, `static/style.css`
- `scripts/web/{make_dev_db,run_ui,verify_ui}.py`
- `WEIGHTED_RANKING_PLAN.md`, `DATABASE_DESIGN_NOTES.txt`

## Verification (end to end)

1. `python scripts/web/make_dev_db.py`, then check the printed NULL-ic counts and the placeholder warning.
2. `TEXTMINING_DB=db/atlas_dev.db python scripts/web/verify_ui.py`: all sections pass, including 7.
3. `python scripts/web/run_ui.py --db db/atlas_dev.db`, then `curl`:
   - `/mirna/MIMAT0000076?type=DISEASE`: no *neoplasm* / *disease* / *cancer* in the first rows; HCC and
     colorectal cancer present (matches the notebook top-10 for miR-21);
   - the same with `&sort=evidence`: *neoplasm* first (old behaviour);
   - `/mirna/MIMAT0000076` (All tab): relevance order plus the calibration note;
   - `/term/MONDO_0004992?sort=relevance` (cancer, expanded): loads, and "matched via" is consistent;
   - `?sort=bogus`: falls back to relevance; pager links keep `type` and `sort`.
   - `/associations?type=DISEASE`, and the same with `&sort=evidence&organism=&level=`: filters apply,
     page 2 keeps every parameter, and a repeat request is fast (cache).
4. `python -m unittest discover -s tests`: still green.
5. After the rerun's real build: rerun `verify_ui.py` against `db/atlas.db`; NULL-ic count must be 0.
