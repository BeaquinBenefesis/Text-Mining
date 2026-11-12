# `atlas.db` — tables, loaders, and build order

Practical companion to `DATABASE_DESIGN_NOTES.txt` (which argues the decisions) and
`DATABASE_IMPLEMENTATION_PLAN.md` (which tracks what is done). This file answers three
questions: **what is in the database**, **what puts it there**, and **why it happens in
that order**.

Everything here describes the build of 2026-09-11 from `outputs/full_run/`.

---

## 1. The shape of the thing

`atlas.db` is a single SQLite file, **1.75 GB**, built once and then served read-only. It is
entirely **derived** — every row comes from a file on disk, nothing is authored in the
database, and the whole thing is dropped and recreated by one script. That is the property
that makes it cheap to change the scoring function later.

It is built from four kinds of input:

```
outputs/full_run/full_run.assoc   59 MB   scored miRNA-term pairs      -> association
outputs/full_run/full_run.cooc   1.6 GB   one row per co-occurrence    -> article, sentence,
                                                                          association_evidence
outputs/full_run/full_run.norm  18.5 GB   one row per normalized hit   -> mir_mention_article
miRBase mappings + 5 OBO ontologies       reference data               -> entity, synonym,
                                                                          ontology_closure,
                                                                          mirna_name_history
PubMed/PMC metadata CSVs                  article year + journal       -> article (backfill)
```

Note the asymmetry: the 18.5 GB `.norm` contributes a 174 MB table, and the 1.6 GB `.cooc`
contributes most of the file. The database is an aggregate, not a copy of the pipeline
output.

---

## 2. Build order, and why it is that order

`python -m textmining.db.build_db` — **16 minutes** end to end. Every arrow below is a hard
dependency, not a preference; with `PRAGMA foreign_keys = ON` most of them are enforced by
SQLite rather than by discipline.

```
 0:02  load ontology graphs (5 OBO caches — TAXON deliberately skipped, §3)
         │  needed by entity, synonym and closure
         ▼
 0:02  read miRBase name history TSVs into memory
         │  entity needs the `dead` flag from it before it can insert a single row
         ▼
 0:01  entity ────────────── everything joins to this; ids are minted here
         │
 0:01  synonym               needs entity ids
 0:03  mirna_name_history    independent, but read once and reused
 0:00  legacy synonyms       needs entity ids AND the conflict set from history
         ▼
 0:17  association           needs entity ids to resolve accessions
         │
         ├─► 8:01  corpus (article + sentence + association_evidence)
         │           needs association ids to attach evidence to
         │
         └─► 0:04  ontology_closure
                     its observed-term set IS `SELECT DISTINCT term_entity_id
                     FROM association` — it cannot run earlier
         ▼
 4:40  mir_mention_article   needs article rows to exist, and INSERTS the 46,963
         │                   articles the corpus never saw
         ▼
 3:02  article metadata      backfills year/journal for ALL articles — must run after
         │                   mentions or those 46,963 stay undated
         ▼
 0:00  corpus_year           needs article.year to count
         ▼
 0:03  search_name           reads association, ontology_closure, synonym AND
                             mir_mention_article — necessarily last
```

Three orderings are worth understanding because they are not obvious:

**`association` before `ontology_closure`.** The closure is built over *observed* terms
only, not the full ontology (§4 of the design notes). "Observed" is defined as "appears as
`term_entity_id` in `association`", so the association table must already exist. This is
what keeps the closure at 91k rows instead of millions.

**`mir_mention_article` before `article_metadata`.** The mention layer spans 320,963
articles; the corpus loader only created the 273,702 that produced a co-occurrence. If
metadata ran first, those 46,963 extra articles would have no `year` and would be invisible
on every timeline. Putting mentions first means the metadata pass picks them up for free —
articles with a year went from 240,539 to **281,435**.

**The whole build is one transaction.** `build_db.py` wraps everything in `with ... con:`,
so a failure at minute 15 rolls back cleanly rather than leaving a half-built file. The cost
is that you cannot inspect intermediate state; the benefit is that a published `atlas.db` is
never partial.

---

## 3. Tables

### The original seven

| table | rows | what it is |
|---|---:|---|
| `entity` | 152,372 | miRNAs and ontology terms in one table |
| `synonym` | 182,309 | every surface form of an entity |
| `association` | 1,300,530 | scored (miRNA, term) pairs — the knowledgebase proper |
| `ontology_closure` | 91,096 | ancestor→descendant, over observed terms only |
| `article` | 320,963 | one row per PMID/PMCID |
| `sentence` | 2,851,057 | text of sentences backing an association |
| `association_evidence` | 17,936,913 | one row per (miRNA span, term span) pair |

**`entity` is one table for two very different things** — miRNAs and ontology terms —
deliberately. Type-specific columns (`reference_level`, `organism`) are NULL for MONDO
terms, `source` is `mirbase` or `mondo`/`go`/`cl`/`bto`/`pw`. The payoff is that
`association` has a single foreign-key target on both sides and the UI can stay generic over
entity types. The cost is six mostly-NULL columns, which is cheaper than the join.

**TAXON is deliberately not loaded at all.** Taxa are disambiguation context for miRNA
normalisation — `NormalizationContext.get_taxon_relevance()` decides which species prefix a
bare `mir-21` resolves to — but that happens at *extraction* time, upstream of this database.
By the time `.norm` exists the species is baked into the accession, and nothing here consults
a taxon: measured 0 associations on either side, 0 closure rows, 0 mentions, against
2,854,488 entity and 2,970,884 synonym rows and 27.5 s of graph load. Skipping it removed
~690 MB and ~40 s from the build. §4 of the design notes had already excluded taxonomy from
the closure for the same semantic reason; loading entities that can never be an association
target was the leftover inconsistency.

The organism dimension is not lost — `entity.organism` carries it, derived from the miRBase
prefix. If a taxonomic rollup is ever wanted, §4 specifies a curated **~30-row** table, not
2.85M entities.

**`association_evidence` has no `norm_status` column** because every row here passed
`normalized_successfully()` upstream, so the value would be a constant. It also has no
sentence text — that lives in `sentence`, deduplicated, because one sentence commonly backs
several span pairs (the largest association: 23,810 evidence rows over 16,228 sentences).

### The four added for the UI

#### `mir_mention_article` — 3,694,133 rows

```sql
CREATE TABLE mir_mention_article(
    mir_key     TEXT    NOT NULL,   -- accession, or surface name when blacklisted
    article_id  INTEGER NOT NULL,
    blacklisted INTEGER NOT NULL,
    PRIMARY KEY (mir_key, article_id),
    FOREIGN KEY (article_id) REFERENCES article
) STRICT;
```

**Why it exists.** `association_evidence` cannot answer "how often was this miRNA
mentioned". It only contains sentences where a miRNA co-occurred with an ontology term, so a
timeline built from it silently omits every methodology, target-validation and biomarker
paper that names no partner term in the same sentence. It answers "how often was this miRNA
*annotated*" — a different question, and not the one the research timeline claims to answer.

**Why `mir_key` is TEXT and not a foreign key.** This looks like a mistake and is not. A hit
whose name is an ambiguous miRBase identifier gets `norm_status = IN_BLACKLIST` and
`normalized_id = None` — it has no accession, so a foreign key would make it unstorable. But
storing it is the entire purpose: those mentions exist nowhere else in the schema.
For those rows `mir_key` holds the lowercased surface name instead, rebuilt to match exactly
the name `MirNormalizer` tested against its blacklist. 140,614 blacklisted hits collapse to
30,851 (name, article) pairs here.

**Why pairs and not counts, or full mentions.** Three granularities were possible: yearly
counts (240,754 rows), (miRNA, article) pairs, or every mention with positions (19.4M rows).
Counts give a chart that cannot be clicked through to the articles behind a bar. Full
mentions roughly double the file to buy flexibility rather than a named feature. Pairs sit in
between and counts derive from them with a `GROUP BY`, so nothing is lost by stopping here.

#### `corpus_year` — 52 rows

```sql
CREATE TABLE corpus_year(year INTEGER PRIMARY KEY, n_articles INTEGER NOT NULL) STRICT;
```

The denominator for share normalisation, and the most important 52 rows in the database
relative to their size.

**Why timelines must be normalised.** The corpus is **99% post-2010** (pre-2010: 2,499
articles, 1.0%) and **46% post-2020**. So a raw per-year mention count is dominated by when
the corpus has coverage, not by when a miRNA was studied. Measured on the 20 most-associated
human miRNAs, the raw curve peaks in 2021 or 2022 for **20 of 20** — every miRNA looks like
it is currently trending, because the corpus is. Dividing by that year's article total
disperses the peaks across 1998–2025 (only 5 of 20 at 2021+), which matches the real history
of the field.

It is trivially derivable from `article`, so materialising it is a choice: it is read on
every timeline render, and having it in the DDL makes the normalisation visible to anyone
reading the schema rather than buried in application code.

#### `mirna_name_history` — 544,564 rows

```sql
CREATE TABLE mirna_name_history(
    mirna_name      TEXT    NOT NULL,
    accession       TEXT    NOT NULL,
    version         TEXT    NOT NULL,   -- 'v9_2', 'v22'
    version_rank    INTEGER NOT NULL,   -- 9002, 22000 — sortable
    dead            INTEGER NOT NULL,
    reference_level TEXT    NOT NULL,   -- 'mature' | 'precursor'
    PRIMARY KEY (mirna_name, accession, version)
) STRICT;
```

Loaded verbatim from `mirna_mature_history.tsv` and `mirna_precursor_history.tsv`. It earns
its place three times over:

1. **Legacy names become searchable.** 8,421 of 49,440 mature and 1,329 of 39,314 precursor
   accessions have carried more than one name, so searching `hsa-miR-34b*` finds
   `MIMAT0000685`. Before this, miRNA synonyms were skipped entirely — `mir_regex.syn` holds
   regex patterns, not surface forms, and no literal source had been identified.
2. **`entity.obsolete` gets a source.** The miRBase mapping TSVs carry no dead signal; these
   files do.
3. **ID conflicts get a disambiguation view** instead of being silently dropped.

`version_rank` is the only computed column. Without it the conflict page sorts releases
lexically and puts `v10` before `v9`.

`reference_level` on every row is **load-bearing, not descriptive**. miRBase distinguishes a
hairpin from its mature product by capitalisation alone — `hsa-mir-34b` is the precursor,
`hsa-miR-34b` the mature strand. Conflicts must therefore be detected *within* a level;
grouping case-insensitively across both collapses the two namespaces and reports **24,768**
false conflicts instead of the real **274**. Grouping within a level reproduces the
normalizer's actual blacklist set-identically (218 distinct lowercase names).

#### `search_name` — 147,520 rows

```sql
CREATE TABLE search_name(
    name_lower   TEXT    NOT NULL,
    display_name TEXT    NOT NULL,
    entity_id    INTEGER,             -- NULL when kind = 'conflict'
    kind         TEXT    NOT NULL,    -- 'primary'|'synonym'|'legacy'|'conflict'
    FOREIGN KEY (entity_id) REFERENCES entity
) STRICT;
```

A flattened union of primary names, synonyms, legacy miRBase names and accessions,
restricted at build time to **reachable** entities: terms that have associations or appear as
a closure ancestor, and miRNAs that have mentions. Ontologies define far more terms than any
corpus mentions, so this keeps unhit terms out of the search path. 147,520 rows over 49,525
entities — roughly a third of `entity`.

`entity_id` is nullable so an ambiguous identifier can be a search *result* that resolves to
no entity and routes to the disambiguation page. `kind` lets the UI say "matched
*hsa-miR-34b\**, a former miRBase name".

A plain table with a lowercase column was chosen over **FTS5**: prefix matching is all the UI
needs, FTS5 adds a virtual-table dependency, and at this size a range scan is ~1 ms.

### Indexes

The database had **none** beyond UNIQUE autoindexes; the miRNA timeline took 5.6 s and
evidence lookups scanned 17.9M rows. There are now eight, seven of them routine. One is not:

```sql
CREATE INDEX ix_ae_assoc ON association_evidence(association_id, sentence_id);
```

The obvious index is `association_id` alone, and it is wrong here. The evidence view pages by
*distinct sentence*; a single-column index yields rowids that each need a random row fetch
just to read `sentence_id` — **2.9 s per page**. With `sentence_id` in the index the page is
an ordered range scan: **0.017 s**. Same rows, 170×, purely from whether the index covers the
query.

---

## 4. Loaders

All in `src/textmining/db/loaders/`, sequenced by `src/textmining/db/build_db.py`. The
convention is **one function per table**, with one exception noted below, and **one script**
that sequences them — loading a table in isolation is a debugging convenience, not the
interface.

| loader | writes | reads |
|---|---|---|
| `entity.py` | `entity` | miRBase mappings, OBO graphs, name history |
| `synonym.py` | `synonym` | OBO graphs, name history |
| `mirna_history.py` | `mirna_name_history` | the two history TSVs |
| `association.py` | `association` | `.assoc` |
| `corpus.py` | `article`, `sentence`, `association_evidence` | `.cooc` + corpus `.sent` |
| `ontology_closure.py` | `ontology_closure` | OBO graphs + `association` |
| `mentions.py` | `mir_mention_article`, `corpus_year` | `.norm` via duckdb |
| `article_metadata.py` | `article` (update) | PubMed/PMC CSVs |
| `search.py` | `search_name` | the database itself |

**`corpus.py` writes three tables in one pass**, breaking the one-function-per-table rule for
a reason: `EvidenceAggregator` folds each co-occurrence into a running per-article sum and
discards the object immediately, so by the time an association has a final score no
individual co-occurrence survives to build an evidence row from. Evidence therefore cannot
be reconstructed from a DB query or from post-aggregation objects — it has to consume the
`.cooc` file directly, and while streaming that file it is already holding everything the
three tables need. Splitting it would mean three passes over 1.6 GB.

**`mentions.py` uses duckdb, and only at build time.** Reading an 18.5 GB TSV in Python is
impractical; duckdb does the scan and aggregation in **92 s** (91 s of which is the raw
read — the aggregation is ~1 s) and hands back 3.7M rows, which Python inserts in batches of
500k. duckdb is never imported by anything that serves a query.

**`search.py` reads the database rather than a file.** It runs last precisely because its
input is everything the other loaders produced.

**`mirna_history.py` is also a library, not just a loader.** `conflicted_names()`,
`latest_row_per_accession()` and `read_history()` are consumed by `entity.py` and
`synonym.py`; the history TSVs are read once in `build_db.py` and the parsed rows passed
around, rather than each consumer re-parsing 544k rows.

---

## 5. Rebuilding and checking

```bash
python -m textmining.db.build_db        # ~17 min, drops and recreates db/atlas.db
python scripts/web/verify_ui.py         # 22 checks over the result
```

`build_db.py` has one variable to change when pointing at a different pipeline run:

```python
output_name = 'full_run'   # swap this
```

`verify_ui.py` checks row counts, that the UI's queries use indexes rather than scanning,
that highlight offsets land on real surface forms, that closure expansion aggregates with
`MAX` rather than summing, that an ambiguous identifier still has a timeline despite having
no associations, and that share normalisation actually removes the recency bias. A build that
fails these should not be served.

---

## 6. Known issues

- **0.56% of evidence rows have a 1-character term span** (99,560 of 17,936,913). A single
  letter or digit was matched as a term, and they resolve overwhelmingly to ontology *roots*
  — `'2'` → disease (MONDO_0000001), `'A'` → cell (CL_0000000), `'A'` → pathway
  (PW_0000001). This is an upstream synonym/abbreviation-resolution defect, not a rendering
  one; the UI faithfully highlights what the pipeline produced. Note that **2-character
  spans are legitimate** and account for 7.9% — they are real ABBREVIATION synonyms (`GC`
  gastric cancer, `OA` osteoarthritis, `MI` myocardial infarction).
- **Abbreviations sometimes resolve to the ontology root rather than the specific disease**:
  `'AD'` (72,041 rows) and `'PD'` (37,791) both map to the generic `disease` term rather
  than Alzheimer's and Parkinson's. Same root cause as above.
- **Indexes are created before bulk loading, not after.** They live in `schema.sql`, so they
  exist while 17.9M evidence rows are inserted — each insert maintains the b-tree, and the
  result packs less densely than a post-hoc build (`ix_ae_assoc` is 315.7 MB built during
  load against 278.3 MB rebuilt afterwards, ~37 MB and some build time). Moving the
  `CREATE INDEX` statements into the build script after loading would recover both.
- **`association.term_type` is denormalised** from `entity.entity_type`. Justified — it is in
  the hot filter path — but it is a duplicated fact, and no loader or validator enforces the
  two agree. They do agree in the current build (0 disagreements), by construction rather
  than by check; §8.5/§9.2 assign this to `validate.py`, which is still unwritten.
- **`entity.obsolete` is still 0 for all ontology terms** — confirmed: all obsolete rows are
  miRNAs. OBO `is_obsolete` is not read, so a term retired from MONDO looks current.
- **Timelines are not materialised** despite §8.3 specifying `mention_timeline` and
  `association_timeline`. Both are one indexed `GROUP BY` (~5 ms), so materialising them
  would add two things to keep consistent for no gain. Deliberate departure, recorded in
  §11.2 of the design notes.

### Resolved

- ~~`ix_entity_type_org` unused~~ — dropped (49.9 MB). The schema now carries a comment
  saying why it is absent, so it does not get re-added.
- ~~`mir_mention_article` stored twice~~ — now `WITHOUT ROWID`: 174.2 MB (83.7 table +
  90.5 autoindex) → **78.7 MB**, one b-tree.
- ~~TAXON loaded but unreferenced~~ — skipped entirely (see §3).
