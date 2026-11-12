# Database structure: evaluation

Date: 2026-11-02. Database: `db/atlas_labeled_fix.db` (7.8 GB), read-only.

The review was read-only and changed no repository or `db/` files. Findings 1, 2 and 5 were checked a second time against the code and gene counts; everything else comes from one review pass. Size savings are extrapolated from samples (1.55M evidence rows, 1M mention pairs, 640k label rows). Numbers will change after the final build.

## Verdict

- **Works well:** the structure is correct, and SQLite is the right choice for a read-only, single-file database built once per run.
- **Correctness:** no orphaned rows and no mismatches in the stored values that were checked.
- **Speed:** median page queries take about 0.1 ms once cached and 6–9 ms when not cached.
- **Intuitiveness:** the five layers are sound at table level. Column names are less clear, because `n_articles` and `score` mean different things in different tables.
- **Size:** about 40% larger than needed (about 7.8 GB vs. 4.6 GB), mostly from redundant data the UI never reads.
- **Biggest problems:** they are in the interface and the gene results, not in the table structure.

## Measurements

Sizes come from `dbstat`.

| Object | MB | Note |
|---|---:|---|
| `association_evidence` + `ix_ae_assoc` | 2,622 | 50 B/row; 58.5% of rows are GENE |
| `mention_pair` | 1,847 | The UI reads only `label` and `confidence` |
| `sentence` + 2 indexes | 953 + 140 | |
| `association` + 3 indexes | 539 + 615 | |
| `association_label` + PK index + `ix_assoc_label` | 680 | Same data stored three times |
| All indexes | ~2,340 | 30% of the file |

Timings use the real `queries.py` functions and exclude HTML rendering. "Uncached" means the file was evicted from the NFS client cache; the server cache may still help, so a truly cold read could be slower.

| Query | Cached | Uncached |
|---|---:|---:|
| `mirna_associations`, miR-21 (18,212 associations) | 37 ms | 1.8 s |
| `mirna_associations`, median | 0.1 ms | 8 ms |
| `mirna_term_clouds`, miR-21 | 97 ms | 2.0 s |
| `term_mirnas`, largest (21,065 associations) | 40 ms | 3.0 s |
| `term_mirnas`, median | 0.1 ms | 9 ms |
| `association_evidence`, largest (23,293 rows) | 34 ms | 6.8 s |
| `association_evidence`, median | 0.1 ms | 6 ms |
| Evidence total + page IDs, current | 35 ms | 6.9 s |
| Evidence total + page IDs, without the `mention_pair` join | 1.1 ms | 31 ms |
| `top_associations`, per uncached page | 0.85–3.0 s | 13–16 s |
| `organisms`, once per process | 1.9 s | 15 s |
| `labels_by_type`, once per process | 0.64 s | 12 s |
| `search("a")` | 56 ms | 2.5 s |

Query plans (`EXPLAIN QUERY PLAN`, for the queries traced):

- Full table scans occur only in the global lists (`top_associations`, `labels_by_type`). `organisms` scans a covering index.
- An empty `IN ()` on propagated pages also shows `SCAN ae`, but it is harmless (0.5 ms).
- Never chosen: `ix_assoc_label`, `ix_sentence_article`, `ix_synonym_entity`.

Integrity checks, all clean:

- All 52.0M evidence rows match `mention_pair` on `sentence_id` and spans, with no duplicate (association, pair).
- `n_direct_articles` matches the evidence for all 5,885,933 associations that have evidence.
- `dominant_label` recomputes with 0 differences.
- `term_type` matches on both tables.
- `foreign_key_check` passes on all tables except the evidence table, which the checks above cover.
- `mirna_stats` shows no drift on 500 sampled miRNAs, and its breadth matches for all rows.
- `mir_key` has 0 unresolved keys.
- Foreign keys are enforced at build time (`connect.py`).

## Findings

### 1. High: propagated associations are a dead end in the UI

- 3,670,053 associations are propagation only: 66.8% of ontology associations and 74% of disease associations.
- The notice at `association.html:33-36` links back to the term's page, which lists miRNAs, not subterms.
- `03-methods.tex:823` claims every score and association is traceable to its sentences. The interface can't show this.
- The data can trace them. On 5,000 propagation-only and 3,000 partial associations, the union of articles through `ontology_closure` equalled `n_articles` in every case.
- A drill-down query takes 57 ms on the largest case (mir-21 → "disease by body system", 1,037 subterms). No schema change is needed.

### 2. High: most human miRNA–gene associations point to non-human genes

| Gene organism | Associations with hsa miRNAs |
|---|---:|
| human | 515,546 (40%) |
| mouse | 338,730 |
| rat | 151,008 |
| bovine | 132,099 |
| fly | 131,159 |
| yeast | 9,322 |
| **Total** | **1,277,864** |

- `entity.organism` holds two vocabularies (`hsa` for miRNAs, `human` for genes; `core.sql:8`), and the filter applies only to the miRNA (`queries.py:369`). So "hsa" on a gene list can show yeast genes.
- The cause is unknown: real species mismatch, ambiguous names, or both. See `GENE_RESOLUTION_NOTES.md`. The unset `default_taxon` from the thesis TODO list may play a part, but this is a guess.
- This could affect the results, not just the display.

### 3. Medium: counts mean different things without saying so

- `association.n_articles` includes propagation, while labels, timelines and sentences are direct only. The timeline heading doesn't say so for the 429,253 partial associations.
- Undated articles disappear silently through the `corpus_year` join (`queries.py:153-154`, `167`): 46,796 of 347,035 evidence articles (13.5%).
- `mirna.html:26` shows "articles mentioning" as 35,503 for miR-21, while the true count is 38,955.
- `score` in `association` and in `mirna_stats` are unrelated quantities.

### 4. Medium: redundant storage

- Evidence spans are fully derivable from `mention_pair` (0 mismatches in 52M rows).
- No code reads the `p_*` columns except one consistency check at `verify_ui.py:303`.
- `mention_pair.term_type` has no UI reader.
- `association_label` repeats the mistake that `core.sql` documents fixing for `mir_mention_article`.

### 5. Medium: the evidence query undoes its own index

The query at `queries.py:451-456` always joins `mention_pair`, even with no label filter. `ix_ae_assoc` therefore stops being covering, despite what the comment in `core.sql` implies. Each row needs two random reads, which causes the 6.9 s uncached time.

### 6. Low: root terms are an exception to propagation

`analysis.py:158-160` skips ancestors with IC 0. "disease" has only 1,724 direct associations (at most 171 articles), while its descendants hold far more. Three other roots have empty term pages. A sample of 20,000 non-root associations showed no such gaps.

### 7. Low: readability

- Prefixes are mixed (`mir_` and `mirna_`).
- `mention_pair` sits in the evidence layer, while the "mention layer" holds other tables.
- Comments are stale: `queries.py:587` says 1.3M associations and 0.32 s, and `core.sql` says 23,810 and 17.9M.
- `DATABASE_DESIGN_NOTES.txt` opens with a PostgreSQL decision that was later superseded, so a reader must follow many amendments.

### 8. Low: no provenance

The file records neither its run nor its configuration. The `build_meta` table from design notes section 8.2 no longer exists.

### Not a defect

`score` differs from `log2(1 + E)` by at most 1.2e-4, because of `.4f` output (`results_io.py:260-261`). Three rows have E = 0.0.

## Recommendations

### Before the final build, in this order

1. Investigate the non-human genes and set a policy, at minimum a same-species filter. Report the 60%. This comes first because it can change the results.
2. Add a page listing the subterms behind a propagated association (estimated at about 1 hour, no schema change).
3. Remove the `mention_pair` join when no label is set. The later row-fetch step still needs it.
4. Label timelines as "direct, dated articles", show undated counts, and fix the miR-21 count.
5. Small changes:
   - make `association_label` `WITHOUT ROWID` (−230 MB);
   - drop `ix_assoc_label` (−225 MB) and `ix_sentence_article` (−60 MB);
   - add a small `build_meta` table with run, date and alpha;
   - fix the stale comments.

### Only if time is left

These two were pre-build fixes in the original review. They moved here because size isn't a real problem for a read-only database, and they touch working queries shortly before the final build.

- Make `association_evidence` `WITHOUT ROWID` on `(association_id, sentence_id, mention_pair_id)` and read spans through the join: 2,622 → ~980 MB (−1.64 GB). This changes the loader and a few queries, and `verify_ui.py` needs updating.
- Reduce the `p_*` columns, choosing one:
  - drop them and `mention_pair.term_type` (−1.1 GB); the `.labels` file keeps the probabilities, and the thesis text needs adjusting;
  - store them as integers × 10,000, lossless given `.4f` (−0.8 GB).
- Drop `ix_assoc_mir_score` (−220 MB). `INDEXED BY` tests showed no gain from it for `mirna_associations`. Re-time `mirna_term_clouds` first, because this query was not tested.

With all of the above, the file goes from about 7.8 GB to about 4.4 GB.

### Mention as limitations or future work

- `top_associations` scans 9.56M rows per uncached page, a direct cost of computing relevance at query time.
- Direct and propagated evidence mass can't be separated in the database, so propagation on/off comparisons need separate runs.
- Slow uncached reads on NFS.

### Leave as they are

- **SQLite with `immutable=1`:** PostgreSQL adds a server with no benefit, a graph database is unnecessary given the closure table, and DuckDB would suit only the global scans. This is a judgement; no alternatives were benchmarked.
- **`mir_key` as a soft reference:** justified and clean.
- **`association.term_type`:** 68 MB, 0 mismatches, and it avoids a join on every list.
- **`score`:** redundant but consistent and indexed.
- **`synonym`** (116 MB): unused by the UI but the source of `search_name`.
- **Others:** the `search_name` conflict rows, `mirna_stats`, `corpus_year`, and `ontology_closure` (4 MB).

## Effects on the thesis

- `03-methods.tex:823`: "every score and association traceable" stays false until the subterm page exists.
- Don't claim that an evidence page is read directly from the index unless the join is removed. Even then, this only covers the total count and page IDs.
- The graph database rejection is supported, but only as a judgement.

## Not verified

- `evidence_mass` was not recomputed, so only the article-count side of propagation is checked.
- The propagation checks on non-direct cases are samples.
- `ANALYZE` was not tested (there is no `sqlite_stat1`). The plans look right without it.
- Gains from building indexes after loading were not measured; the design notes report about 12% on `ix_ae_assoc`.
- Scratch-sample timings ran on local disk, so only sizes are reported from them.
