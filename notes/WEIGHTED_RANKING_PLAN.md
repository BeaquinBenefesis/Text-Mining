# Weighted ranking (evidence × specificity): implementation plan

Status: planned 2026-09-16; pipeline, schema, loaders and UI implemented 2026-09-17 (UI tested on a migrated dev DB).
Decision record: `DATABASE_DESIGN_NOTES.txt` §16.5. Evidence: `IC_THRESHOLD_ANALYSIS.md` §9.

---

## 1. The IC measure: `entity.ic`

Specificity of a term, derived from the ontology's shape.

- `IC = −ln(c / N)`, with `c` = descendants + 1 and `N` = nodes in the restricted graph.
  This is `OntologyGraph.compute_ic_from_index`.
- Stored **normalised**: `ic = IC / ln N = 1 − ln c / ln N`, in [0, 1].
  - Root = 0, leaf = 1.
  - Examples: *disease* 0.00, *neoplasm* 0.19, *cancer* 0.25, *breast cancer* 0.56, *HCC* 0.76.
- Depends only on the ontology release, roots and relationship set. **Stable across corpus builds.**
- Literature name: intrinsic / structural IC (Seco et al. 2004).
- The column is named `ic`; its schema comment must say **normalised**. `ontology.py`
  also calls the raw `−ln(c/N)` "IC", and mixing the two gives values outside [0, 1].

### Dropped: corpus IC (`ic_corpus`)

Corpus IC is the share of articles mentioning the term or any descendant,
`log2(A/df) / log2(A)` (Resnik 1995, IDF with propagation).
It was prototyped (`IC_THRESHOLD_ANALYSIS.md` §9.3) and **will not be stored**:

- it predicts the annotation labels worse than structural IC in every ontology
  (GO 0.63 vs 0.78, CELL 0.67 vs 0.80, DISEASE 0.45 vs 0.71 AUC);
- it made the miR-21 rankings worse;
- storing an unused column costs a loader, validation and UI surface for nothing.

The prototype stays in `outputs/ic_threshold_term_annotated/analysis_scripts/corpus_idf.py`
for the methods chapter (*disease* in 69% of articles, *cancer* 41%). Revisit only if a
DISEASE-specific two-feature cutoff is ever pursued.

---

## 2. Scope and ranking formula

- **Ranking (decided 2026-09-17):** relevance = **E · ic^α, α = 2 (provisional)**, computed at query time.
  - `E = association.evidence_mass`: the evidence before the outer log, `score = log2(1 + E)`.
  - Displayed as `log2(1 + ic^α · E)`, in the same units as `score` and never above it.
  - Why not `score × ic`: since `score = log2(1 + E)`, it ranks by `(1 + E)^ic`, so IC acts as an
    **exponent** on the evidence and the exchange rate grows with evidence (a leaf with 10 articles
    ties with *cancer* at 14,640). `E · ic^α` is a **constant** exchange rate: halving IC costs 2^α
    times the evidence.
  - Why α = 2 (top-10 over 1,021 human miRNAs with ≥ 50 DISEASE associations, atlas.db 2026-09-11):
    miRNAs with *disease/neoplasm/cancer* in the top-10: raw 100%, α = 1 93%, α = 2 4%, `score × ic` 0%.
    `score × ic` also drops miR-21's best-supported specific cancers (colorectal, breast, lung) for
    terms with ~10× less evidence; α = 2 keeps them. Notebook: `analysis/ic_distribution.ipynb`.
- **`association.score` is unchanged:** it stays "amount of evidence". `evidence_mass` is stored next to it.
- **No minimum-article guard (decided):** all evidence is kept and ranked. `n_articles` is shown, not filtered on.
- **Sorts:** `relevance` (default) and `evidence`. The "specificity" sort is dropped: it is the α → ∞
  limit of the same family, and every leaf ties at IC 1.00.
- **All-types lists** (miRNA "All" tab, `/associations`) also rank by relevance, with a note that
  normalised IC is not calibrated across ontologies (GO-BP crossover ~0.50 vs DISEASE ~0.28).
- **Not in scope:**
  - the load-time IC floor (§14.4, still open; waits for own round 2 labels);
  - cross-ontology calibration of IC (per-ontology rescale around the crossover; after round 2);
  - corpus IC in any form (§1);
  - noise handling for fixed phrases like "tumor suppressor" (§16.3);
  - collapsing ancestor/descendant pairs that both appear in one top list.

---

## 3. Pipeline: article counts and evidence mass per association

`n_articles` counts **propagated** contributions too (propagated associations have no
`association_evidence` rows, §5.2); `n_direct_articles` counts only articles with direct evidence.

- **`models.py`, `AssociationEvidence`**
  - [x] `_n_articles` / `_n_direct_articles`, incremented in the flush inside the `epoch >= 0` branch;
    the pending article is added in the properties.
  - [x] `is_inferred` flag from the aggregator marks propagated contributions.
  - [x] `evidence_mass` property (`_corpus_sum + log2(1 + pending)`); `score = log2(1 + evidence_mass)`.
  - [x] `Association` forwards `n_articles`, `n_direct_articles`, `evidence_mass`.
- **`results_io.py`**
  - [x] `.assoc` columns `evidence_mass`, `n_articles`, `n_direct_articles`; old files fail with a KeyError.
- **Verified** on a 1.5M-line `.norm` slice: both counts match an independent recount from `.cooc`
  (0 mismatches over 276,734 associations).
- **Tests (`tests/test_evidence_propagation.py`)**
  - [ ] One article, several co-occurrences → count 1.
  - [ ] Two articles → 2.
  - [ ] Article that only reaches the ancestor via propagation → counted in `n_articles`, not in `n_direct_articles`.
  - [ ] Last article still pending → counted.
  - [ ] `score == log2(1 + evidence_mass)`.

---

## 4. Schema: `src/textmining/db/schema/core.sql`

- **`entity`**
  - [x] `ic REAL`: normalised structural IC; NULL for MIR. (TAXON isn't loaded as a target type, so no rows.)
  - [x] Fix the comment: say "normalised structural IC (IC / ln N) on the restricted graph, in [0, 1]".
  - [x] **Move `n_articles` and `n_articles_direct` out of `entity`.** They are per-(miRNA, term) counts and belong on `association`. On `entity`, `NOT NULL` without a default also makes every miRNA insert in `loaders/entity.py` fail.
- **`association`**
  - [x] `evidence_mass REAL NOT NULL`: E, before the outer log (§2).
  - [x] `n_articles INTEGER NOT NULL`: supporting articles from §3, direct + propagated.
  - [x] `n_direct_articles INTEGER NOT NULL`: articles with direct evidence (computed in the pipeline, §3).
- **Indexes**
  - [x] **No new index for now.** `ix_assoc_mir_score` still serves the `WHERE mirna_entity_id = ?`; only the ORDER BY becomes a temp sort (§8).

---

## 5. Loaders: `src/textmining/db/loaders/`

### 5.1 `entity.py`: `ic`
- [x] Add `ic` to `_ENTITY_INSERT`; miRNA rows and retired accessions insert `None`.
- [x] In the ontology loop, compute `graph.compute_ic_from_index(idx) / math.log(graph.node_num)` per node.
  - `iter_nodes` yields node data, not indices, so either iterate indices and read the data, or map `node["id"]` via `graph._id_to_idx` (or a public accessor; better to add one to `OntologyGraph`).
- [x] Clamp tiny negatives to 0: `−0.00` shows up for roots due to float rounding.
- [x] Use the **same graph instance** that builds `ontology_closure`, so IC, closure and propagation all share roots and relationships.

### 5.2 `association.py`: `n_articles`
- [x] Read `evidence_mass`, `n_articles`, `n_direct_articles` from the `.assoc` file (§3) and insert them.
- [ ] Dead miRNAs are still dropped silently (comment added). At least log the count.

### 5.3 `corpus.py`: `n_direct_articles`
- Superseded: counted in the pipeline instead (§3).

### 5.4 `build_db.py`
- [x] Call order is unchanged: entity (IC) → … → association → corpus → closure → … → search.
- [ ] Build provenance: record the IC definition (normalised structural), roots and relationships per
  ontology, ontology source hashes, run name and git commit. Not implemented yet.
- [x] Validation: `scripts/web/verify_ui.py` section 7 (`ic` in [0, 1], no `ic` on miRNAs,
  `score == log2(1 + evidence_mass)`, `1 ≤ n_articles`, `n_direct_articles ≤ n_articles`, ranking order).
  Roots have `ic` = 0 only in single-root ontologies (BTO has two roots, 0.02 and 0.25).


---

## 6. Queries: `src/textmining/web/queries.py` (done 2026-09-17)

- [x] Constants `RELEVANCE_ALPHA = 2`, `SORTS = ("relevance", "evidence")`, `LEVELS`; helpers
  `_rank_key(sort)` (`evidence_mass * pow(ic, α)` or `score`), `_relevance()` (display value) and
  `_assoc_columns()`. Only these fixed fragments reach SQL; α is a constant, never user input.
- [x] `mirna_associations(..., sort)`: ORDER BY rank key, then `score DESC, id`. Totals unchanged.
- [x] `term_mirnas(..., sort)`: `hits` joins the term entity and carries `rank_key`; the per-miRNA MAX
  and the final order use it. Docstring updated: under relevance, the descendant a miRNA is listed
  under can differ from its highest raw score.
- [x] `_attach_matched_terms`: same order as the list.
- [x] `get_association` / `get_entity`: return `ic`, `evidence_mass`, `n_articles`, `n_direct_articles`, `relevance`.
- [x] New `top_associations(sort, term_type, organism, level, page)`: global listing, not deduplicated,
  cached per argument tuple (the DB is immutable).
- NULL `ic` (stale ids, dev DB only) gives NULL relevance, which sorts last.

---

## 7. Web: `app.py` and templates (done 2026-09-17)

- [x] `?sort=relevance|evidence` on `/mirna`, `/term` and the new `/associations`; unknown values fall
  back to relevance. `/associations` also takes `type`, `organism` (default hsa) and `level` (default mature).
- [x] `_ranking.html` macros: query strings that keep blank filters, sort toggle, specificity bar,
  article counts "(k direct)", and a help sentence (plus the cross-ontology note on all-types lists).
- [x] `mirna.html`: Term | (Type) | Relevance | Evidence | Articles | Specificity; tabs and pager keep `sort`.
- [x] `term.html`: Best relevance | Evidence | Articles; the term's own specificity in the header;
  notice text updated for propagation and MAX over relevance.
- [x] `association.html`: badges for relevance, evidence, specificity, articles (direct / via subtypes).
- [x] Links to `/associations` from the header and the home page.
- [x] `TEXTMINING_DB` / `run_ui.py --db` to serve another build; `scripts/web/make_dev_db.py` builds a
  migrated copy of an old atlas.db (placeholder `n_articles`, see its docstring).
- Not done: a "general term" badge (waits for the round 2 crossovers).

---

## 8. Efficiency (measured on atlas.db 2026-09-11)

- 1,300,530 associations; mean 50 per miRNA; maximum 2,539.

| query | plan | time |
|---|---|---|
| sort by `score`, LIMIT 25 | index range scan on `ix_assoc_mir_score` | 0.67 ms (largest miRNA 1.26 ms) |
| sort by computed weight, LIMIT 25 | same scan + temp B-tree sort | 3.65 ms (largest 5.77 ms) |

- About 5× slower, but ~6 ms worst case on miRNA pages. Acceptable; no action.
- Measured after implementation (atlas_dev.db, 2026-09-17): miR-21 DISEASE relevance page 4 ms;
  MONDO root expansion (hsa) 1.66 s relevance vs 1.65 s evidence, so the extra join is negligible;
  `/associations` uncached 1.6 s (hsa, mature, all types) and 0.5 s (DISEASE, all), cached ~0 ms.
- **`term_mirnas` on root-level expansions** is the one to profile. The extra `JOIN entity te` costs one rowid lookup per hit, and expanding the MONDO root already materialises a very large hit set (~2 s for the count, per the docstring).
- **Escape hatch, only if profiling demands it:**
  - Stored `association.weighted_score REAL` plus `CREATE INDEX ix_assoc_mir_wscore ON association(mirna_entity_id, weighted_score DESC)`.
  - Restores index-ordered scans.
  - Costs: a rebuild whenever the weighting changes, ~15–20 MB of index, and the loss of query-time tunability.
- Build time: computing `ic` in the entity loader is one IC lookup per term, a few seconds at most.

---

## 9. Evaluation (for the thesis)

- [ ] **HMDD recall@k per miRNA:** `evidence` sort vs. `relevance` sort, with propagation on and off.
  - Caveat: HMDD is disease-only and cancer-heavy, which favours raw score.
- [ ] **Manual top-10 review** for ~5 miRNAs across facets (miR-21, miR-155, miR-122, let-7, one low-evidence miRNA).
- [ ] **Sensitivity** of the top-10 to α ∈ {1, 2, 3}: Jaccard overlap between settings, per ontology
  (GO-BP and CELL may need a different α than DISEASE).
- [ ] **Redo the miR-21 comparison after the rerun.** Propagation raises ancestor scores while their IC stays low, so the balance between the two factors shifts.

---

## 10. Open decisions

- [x] ~~`DEFAULT_MIN_ARTICLES`~~: no guard (§2).
- [x] `n_direct_articles`: built (§3).
- [x] Relevance ties (leaves at IC 1.00): secondary key `score DESC, id`.
- [x] Formula family: `E · ic^α` instead of `score × ic` (§2).
- [ ] **α:** 2 is provisional; confirm with the manual review and the α sensitivity (§9), per ontology.
- [ ] **Cross-ontology calibration** for all-types lists (rescale IC around each ontology's crossover).

## 11. Remaining work

1. §3 count and `evidence_mass` unit tests.
2. §5.2 log dropped dead miRNAs; §5.4 build provenance.
3. After the rerun's build: `verify_ui.py` against the real `atlas.db` (terms without `ic` must be 0).
4. §9 evaluation.
