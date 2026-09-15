# Implementation plan: corpus -> ... -> database

Companion to `DATABASE_DESIGN_NOTES.txt` (design rationale) and `PROGRESS_NOTES.md`.
Goal of this plan: make the path **corpus -> normalized hits -> associations -> queryable DB**
run end to end. Scoring quality is deliberately deferred — see Stage 4.

Guiding principle: **get a thin slice working end to end first, then improve the score.**
A complete-but-crude pipeline is more useful than a well-scored one that stops before the DB.

---

## Stages 0-2 — DONE (kept for the record)

These were the prerequisites, the extraction/scoring decoupling, and carrying the fields the
schema needs. All landed; a full-corpus run is on disk in `outputs/mirna_and_disease/`
(12.0 GB `.norm`, 2.7 GB `.cooc` / 31,410,695 rows, 67 MB `.assoc` / 1,482,996 rows).

- [x] **MIR + MONDO pipeline config** — `MirnaDiseasePipelineConfig`, run via
      `scripts/pipeline/run_mirna_disease_pipeline.py`. MIR + MONDO first because it is the
      pair HMDD benchmarks, so it feeds evaluation directly.
- [x] **Association key confirmed** — `Grouper.extract_cooccurrences` reads
      `hit.normalization.normalized_id`, not `hit.entity_id`. Associations are keyed on the
      normalized accession, so the join to the ontology is sound. This is what
      `association.mirna_entity_id` / `.term_entity_id` resolve from.
- [x] **Ordering contract enforced** — grew from a sentence-order assertion into
      `ArticleStreamGuard` (analysis.py), which checks article contiguity *and* within-article
      sentence order and stamps the `article_epoch` that `AssociationEvidence` uses to detect
      a reordered stream in O(1). Turns two classes of silent wrong answer into loud ones.
- [x] **Rebuild entry point** — `run_from_normalized_output` (pipeline.py): `.norm` →
      associations, no syngrep, no normalization. The single-pass `process_hits` path still
      works; the rebuild path is an addition. This is what makes re-scoring cheap, which
      matters because `section_weigth()` is still a stub.
- [x] **DuckDB read layer** (1.5.5) — `read_normalized_hits` (results_io.py) supplies the
      out-of-core sort matching `NormalizedHit.sort_key`, which is what makes a fresh
      multi-shard read satisfy the ordering contract above.
- [x] **`CoOccurence` carries offsets and `weight`** — `entity_positions` holds (start, end)
      for both sides and `score` is `weight * section_weigth(section_num)`. `weight` is inert
      at 1.0 today and is the injection point for Stage 4 propagation.
- [x] **`.cooc` is persisted** — `write_cooccurrences_tsv`. This is the input to the evidence
      tier and to per-association sentence counts; without it the evidence tier would need a
      full re-extraction.
- [x] **Sentence text: decided, no reader needed.** Store identity only; `ArticleReader`'s
      mmap byte-offset index (article_utils.py:58) *is* the sentence store, resolved at render
      time (design notes §8.4). This closes out the `SENTENCE_READER_DESIGN.md` dependency.
- [~] **Private Postgres** — MOOT, not attempted. SQLite is now load-bearing rather than a
      fallback (§8.1): `immutable=1` and read-only file shipping are SQLite-specific and
      deliberate. (`ATTACH` is no longer part of the argument — see §9: single file for now.)
- [ ] **Remaining:** sanity-check that `run_from_normalized_output` reproduces the inline
      `process_hits` associations on a test corpus. If they differ, the ordering guarantee is
      broken somewhere. Cheap, and worth doing before the loader trusts `.assoc`.

---

## Stage 3 — The database itself (one SQLite file)

Design of record: `DATABASE_DESIGN_NOTES.txt` §9 (one file) amended by §10 (what actually
got built — sentence text reversal, `normalized_hit` dropped, entities-per-sentence cap,
combined corpus loader, article metadata source). Read §10 alongside §9 now.

**3a — Scaffolding** — DONE, apart from `immutable=1`
- [x] `connect.py`: `open_for_build` / `open_readonly`, `uri=True`, `PRAGMA foreign_keys =
      ON` per connection, post-`executescript` sanity check, logging. Verified end-to-end.
- [ ] **Still open:** `immutable=1` on the read-only URI (once shipping, not while rebuilding).
- [ ] `build_meta` table — still not added; not urgent with one file, don't forget once
      there's more than one build to tell apart.

**3b — DDL** (`schema/core.sql`, ONE file, `STRICT` tables) — DONE, all seven tables
- [x] `entity(id, accession, primary_name, entity_type, source, obsolete, reference_level)`
- [x] `synonym(id, synonym_name, synonym_type, entity_id)` — `synonym_type` defaults
      `'STANDARD'`, ABBREVIATION rows tagged the same table (§10 keeps this from 8.3).
- [x] `association(id, mirna_entity_id, term_entity_id, term_type, score, UNIQUE(mirna,term))`
      — minimal on purpose (§8.3's IC/direct-vs-propagated columns deferred, see Stage 4).
- [x] `ontology_closure(ancestor_id, descendant_id, UNIQUE(ancestor,descendant))` —
      **no `min_distance`**: dropped after checking it was never actually consumed by
      anything (propagation uses the IC ratio, not hops; §8.3 already said as much). Built
      over *observed* terms only (`ancestor_closure` scoped by `association.term_entity_id`),
      not the full ontology — per §4.
- [x] `association_evidence(id, association_id, sentence_id, mirna_start, mirna_end,
      term_start, term_end)` — no separate `normalized_hit` table; see design notes §10.2
      for why (`norm_status` would be a constant here, so it's not a column either).
- [x] `article(id, external_id, year, journal)` — `external_id` is a raw PMC id or bare
      PMID (format not disambiguated at the column level, both occur); `year`/`journal`
      both nullable, measured against the real metadata files (§10.5).
- [x] `sentence(id, article_id, section_num, sentence_num, sentence_text)` — text IS
      stored now, reversing 8.4/9 (§10.1 has the reasoning and the real size numbers).
- [ ] **Still open, optional:** `CHECK (reference_level IN (...))` — `STRICT` catches a
      wrong type, not a wrong value.
- [ ] IC columns on `entity`/split score columns on `association`/indexes — all still
      deferred to Stage 4, once propagation exists to populate them from.

**3c — Loaders** — DONE, one function per table (or combined where the data flow forces
it), sequenced by `db/build_db.py`:
- [x] `loaders/entity.py` — `load_entities`: miRBase nodes + every configured ontology
      graph's terms, both halves done. `load_accession_to_id` also lives here (the
      `accession -> id` lookup every later loader needs — this is what "`ids.py`" turned
      into; never needed its own file).
- [x] `loaders/synonym.py` — `load_synonyms`: ontology-term synonyms via
      `OntologyGraph.extract_synonyms()`, `STANDARD`/`ABBREVIATION` both in one table.
      **miRNA synonyms still skipped** — `mir_regex.syn` is regex patterns, not literal
      surface forms; still unresolved, see Still Open.
- [x] `loaders/association.py` — `load_associations(con, associations: Iterable)`, reads
      from `results_io.read_associations_tsv` (new — `Association.score` is a computed
      property over private `AssociationEvidence` state, can't be reconstructed from a
      stored float, so this returns a small duck-typed `ReadAssociation` instead).
- [x] `loaders/ontology_closure.py` — `load_ontology_closure`, must run after
      `association` (derives its observed-term set from it).
- [x] `loaders/corpus.py` — `load_corpus(con, coocs_path, reader)`: **one pass** builds
      `article` + `sentence` + `association_evidence` together, reading
      `results_io.read_cooccurrences_tsv` directly. See design notes §10.4 for why this
      isn't three separate loaders (`EvidenceAggregator` discards per-co-occurrence detail
      once it's folded into a score, so evidence has to come from the `.cooc` file, not a
      DB query or an in-memory object after aggregation).
- [x] `loaders/article_metadata.py` — `load_article_metadata`: streams both metadata CSVs
      once each (`csv.field_size_limit(sys.maxsize)` needed — a real oversized field exists
      in `pmc_metadata.csv`), filtered to only the `external_id`s already in `article`,
      routes PMC-prefixed ids to `pmc_metadata.csv` and bare PMIDs to
      `pubmed_metadata.csv`. Must run after `corpus.py` (backfills rows it just created).
      ~2:48 wall time for a full pass over both files regardless of how many articles are
      being backfilled — dominated by file I/O, not lookup cost.
- [x] `analysis.py` gained `ENTITIES_PER_SENTENCE_CAP = 20` and `CoOccurence.origin_file_name`
      — see design notes §10.3/10.4. **Any existing `.cooc` file predates both and must be
      regenerated** before the evidence tier can be built from it for real.
- [x] `db/build_db.py` — the one runner: opens ontology graphs, then inside one
      `with MultiArticleReader(...) as reader, con:` block runs entity → synonym →
      association → corpus → ontology_closure → article_metadata. Logs each stage plus a
      final per-table row-count summary. Paths for `assoc_path`/`coocs_path` derive from a
      single `output_name` variable (currently `'mirna_and_disease'`) rather than being
      hardcoded separately — swap one line once the full-entity-type run exists.
- [x] `obsolete` — **closed.** `load_mirbase`'s TSVs carry no dead signal but
      `mirna_{mature,precursor}_history.tsv` do; `loaders/mirna_history.py` supplies it and
      also inserts the 1,324 accessions that appear only in history (design notes §11.4).
      Side effect: that recovered 4,760 associations `load_associations` had been dropping
      because their miRNA accession was missing from `entity`.
- [x] Timelines — **built, but not as the two tables §8.3 proposed.** Association
      timelines are derived at query time (`association_evidence` → `sentence` → `article`,
      now indexed). miRNA timelines could *not* be: `association_evidence` only covers
      sentences that produced a co-occurrence, so it answers "how often was this miRNA
      annotated", not "mentioned". `loaders/mentions.py` adds `mir_mention_article`
      (3,694,133 `(mir_key, article_id)` pairs, one 92s duckdb pass over the 19GB `.norm`)
      plus `corpus_year`. See design notes §11.1/§11.2 — and note that timelines **must**
      be normalised by `corpus_year`: the corpus is 99% post-2010, so raw counts peak in
      2021-22 for 20 of the 20 most-studied human miRNAs.
- [ ] `external_association` (HMDD etc.) — not started, Stage 5 territory.

**3d — Validation** (`validate.py`) — not started.
- [ ] What FKs *can't* express: `association.term_type` agrees with `entity.entity_type`,
      `UNIQUE(mirna_entity_id, term_entity_id)` holds, closure acyclic/no self-pairs, score
      columns in range, row counts reconcile against `.assoc`/`.cooc`.
- [ ] Wire it into `build_db.py`: **a build that fails validation is not published.**

**Milestone: 3a-3c are done. 3d (validation) and a real end-to-end run are what's left
before the pipeline is complete.** A `mirna_and_disease` re-extraction is in progress as of
this update (regenerating `.cooc`/`.assoc` with the entities-per-sentence cap and
`origin_file_name` fix) — `build_db.py` hasn't been run against real data yet.

## Stage 4 — Scoring (the deferred quality work)

- [ ] **Implement `section_weigth()`** (scoring.py:21, currently `return 1`).
      Needs a defensible weighting per section — abstract/title vs. body vs. references.
      Check what `scoring_scheme.txt` already commits to.
- [ ] **Token-distance decay** — depends on the offsets added in Stage 2.
- [ ] **Build the closure table** for MONDO (then GO-BP, CL, BTO, PW):
      - collect observed term IDs: `SELECT DISTINCT entity_id FROM '*.norm' WHERE entity_type=...`
      - feed to `OntologyGraph.ancestor_closure()` (ontology.py:266) — it already computes
        exactly the induced subgraph over observed terms plus ancestors
      - materialize as `(ancestor_id, descendant_id, distance)`
      - **taxonomy excluded** — curated ~30-row rollup table instead (§4)
- [ ] **Evidence propagation** (§5) — the main piece:
      - expand at the **article flush point** in `AssociationEvidence._flush_article_evidence`,
        not per sentence (~20x less work, identical result)
      - accumulate the article's direct `(mir, term) -> weight` map first, then expand to
        ancestors once
      - decay = `IC(ancestor) / IC(term)`, from `compute_ic` (ontology.py:301)
      - **must happen before the per-article `log2`** — see §5.2 for why post-hoc summing
        systematically inflates broad terms
- [ ] **Decide structural vs. corpus IC.** `_compute_ic_from_index` (ontology.py:304) is
      structural (descendant count / node count). Corpus-frequency IC may fit propagation
      better since propagation is a claim about *evidence*. Computing both and comparing is a
      cheap, publishable result for the evaluation chapter.
- [x] **Split the score columns** — settled in the Stage 3b DDL, so propagation writes into
      columns that already exist. Needed for the HMDD ablation and for answering "is this
      attested or inferred?".
- [ ] **Prune-at-load thresholds.** Propagation takes `association` from 1.5M rows to an
      estimated 15-30M, at which point `atlas.db` is a lot heavier regardless of file count
      (§8.3). Needs a score floor for propagated rows and an `ic_structural` floor for
      ancestors. The root already falls out at weight 0 by construction (§5.3). This is
      also the point where real numbers exist for the §9.4 file-count question.

---

## Stage 6 — User interface — DONE

Built against `atlas.db`; design rationale and the five findings that shaped it are in
design notes §11. FastAPI + Jinja, server-rendered, read-only immutable connection.

- [x] **Schema additions** — `mir_mention_article`, `corpus_year`, `mirna_name_history`,
      `search_name`, `entity.organism`, and six indexes. `ix_ae_assoc` must be
      `(association_id, sentence_id)`: the single-column form costs 2.9s per evidence page
      against 0.017s (§11.5).
- [x] **Two views** — miRNA-centric (`/mirna/{accession}`: research score, normalised
      timeline, filterable association list) and entity-centric (`/term/{accession}`:
      closure-expanded miRNA list, `MAX` never `SUM`, "matched via" shown).
- [x] **Evidence inspection** — `/association/{id}`, paginated by distinct sentence
      (the largest association has 23,810 rows over 16,228 sentences), miRNA and term
      spans highlighted. miRNA spans are extended at render time; the stored span is the
      3-character stem (§11.7).
- [x] **ID-conflict view** — `/name/{name}` for the 218 ambiguous miRBase identifiers,
      which exist nowhere else in the database (§11.3).
- [x] **Search** — names, synonyms, legacy miRBase names and accessions, restricted to
      reachable entities so the 2.85M TAXON rows stay out.
- [x] **Verification** — `scripts/web/verify_ui.py`, 22 checks.
- [ ] **Not built:** synonym feedback loop (see Still open).

---

## Stage 5 — Evaluation support

- [ ] **Load HMDD into `external_association`** — separate table, never merged (§3b).
      It is the benchmark; merging at load contaminates it.
- [ ] **Overlap / recall query** against HMDD, direct-only and direct+propagated.
- [ ] **Corpus statistics** for the methods chapter, straight from DuckDB over the `.norm`
      files: hit counts per entity type, normalization success rate, per-ontology coverage.
- [ ] Convert `.norm` -> Parquet once the corpus outgrows TSV:
      `COPY (SELECT * FROM '*.norm') TO 'mentions.parquet' (FORMAT PARQUET)`.

---

## Suggested ordering

Stages 0-2 done apart from the rebuild-vs-inline equivalence check. Stage 3a-3c done. Next:

1. **Let the in-progress `mirna_and_disease` re-extraction finish** — regenerating
   `.cooc`/`.assoc` with `ENTITIES_PER_SENTENCE_CAP` and `origin_file_name`. Nothing in 3d
   or a real `build_db.py` run can proceed against stale `.cooc` output.
2. **Run `build_db.py` end to end against the new output.** First real `atlas.db` with
   every table populated. Fix whatever breaks — genuinely untested at full scale so far.
3. **3d — validation script.** Wire the FK-can't-express checks in, hook it into
   `build_db.py` so a failing build doesn't get treated as done.
4. **`mention_timeline`/`association_timeline`** — now unblocked (`article.year` exists),
   still not written. A derived/aggregate step, not a loader.
5. **Then Stage 4**, in order: `section_weigth` (affects every score), closure-based
   propagation, corpus IC, prune-at-load thresholds.

---

## Still open

- **Is a standalone downloadable resource file wanted for the thesis deliverable?** Still
  the one open question that decides one file vs. two, not engineering — ask the
  supervisor. Design notes §9.4 says how to revive the §8 two-file split if needed.
  `atlas.db` is now 2.4GB (was 1.7GB) after indexes and the mention layer.
- **Synonym feedback loop** — named as a work package in `thesis_instructions.txt`,
  deliberately not in the UI's v1. It is the only feature that would make the database
  writable; confirm the omission with the supervisor.
- **Research score weights are provisional** — the volume/breadth weighting is not
  validated. Correlate against HMDD entry count per miRNA (Stage 5) before reporting it.
- ~~miRNA synonyms~~ — **closed.** The miRBase history TSVs are literal surface forms:
  8,421 mature and 1,329 precursor accessions have carried more than one name. 9,970 legacy
  synonyms now load, so `hsa-miR-34b*` finds `MIMAT0000685`. The 218 genuinely ambiguous
  names are withheld and routed to a disambiguation view instead (design notes §11.3/§11.4).
- **`section_weigth()` is still `return 1`** (scoring.py:21) — every score currently
  produced is an unweighted co-occurrence count under a per-article log. Fine as a thin
  slice; not a result to report yet.
- ~~`build_db.py` untested at full scale~~ — **closed.** Run end to end against
  `full_run` on 2026-09-09 (~16 min): 1,300,530 associations, 17,936,913 evidence rows,
  3,694,133 mention pairs, 320,963 articles. `scripts/web/verify_ui.py` checks the result.
- ~~miRNA<->miRNA edges~~ — closed: bipartite only, see design notes §7.1.
- ~~Postgres vs SQLite~~ — closed: SQLite, see design notes §7.3.
- ~~One file vs. two~~ — settled for now: one file (§9). Revisit per §9.4 if triggered.
- ~~OntologyGraph term iteration~~ — closed: `OntologyGraph.iter_nodes()` exists and is
  used by `load_entities`.
- ~~`entity.source` casing~~ — closed: both halves write lowercase (`'mirbase'`, `'mondo'`, ...).
- ~~Sentence text storage~~ — closed, reversed: text is stored (§10.1), not resolved via
  `ArticleReader` at render time.
- ~~`normalized_hit` table~~ — closed: dropped, positions inlined on `association_evidence`
  (§10.2).
