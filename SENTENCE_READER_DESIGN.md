# Design note — indexed, multi-file `SentenceReader`

**Status:** proposal, not yet implemented.
**Motivates:** replacing the current single-file, sorted-order-only `SentenceReader`
(`src/textmining/sentence_utils.py`) with an article-indexed, multi-file reader modeled on
`SynFileReader`/`MultiSynFileReader` (`src/textmining/synonym_utils.py`).

## 1. Problem with the current reader

`SentenceReader.fetch_text` is a single forward-only cursor over one open file. It requires:

- every sentence request to arrive in the same sorted order as the file
  (`(article_id, section, sentence)`, enforced by `check_sorted`), and
- the whole corpus to live in one file.

This works today because `prepare_corpus.sh` guarantees the sentence file is sorted that way,
and every caller happens to walk hits in matching order. But it means the *order in which
hits/articles are processed upstream* is coupled to *the physical layout of the sentence
file* — any caller that wants to process articles out of that exact order (batching, retries,
parallelism across chunks, re-processing a subset) can't use this reader as-is. It also can't
span the multiple `chunk_N.sent` files `prepare_corpus.sh -n` produces.

## 2. Proposed design

### 2.1 Index

A precomputed index, one entry per article per file:

```
article_id    file_id    byte_start    length
```

Built once per sentence file with a single linear pass (mmap + `mm.find(b'\n', ...)`, same
technique as `SynFileReader._index_file_fast`), watching for the point where the article_id
prefix of `sent_id` changes rather than indexing every line. Output is small: one row per
article, not per sentence.

### 2.2 Reader

- `IndexedSentenceReader` — owns one file + its index (mmap, like `SynFileReader`'s
  low-memory mode). Given an `article_id`, seeks to `byte_start`, reads `length` bytes as one
  block, decodes it, and parses every line into `{sent_id: text}`. Caller pulls whatever
  sentence ids it needs for that article out of the dict, then discards it.
- `MultiIndexedSentenceReader` — routes by `file_id` to the right `IndexedSentenceReader`,
  lazily opening file handles/mmaps on first use, mirroring `MultiSynFileReader`.

This drops the sorted-order requirement entirely: fetching article A after article Z is just
another seek, not an error. It also matches how `Processor`/`core.py` already consume the
corpus — article-by-article — so "read one article's block, serve all its hits, discard" is a
natural fit, not a new access pattern.

### 2.3 Batch ordering (IO discipline)

Removing the sorted-order *requirement* doesn't mean requests should actually be issued in
arbitrary order. mmap gives lazy, page-cache-backed access, not free random access: scattered
offsets still cost real page faults / disk seeks if the working set doesn't fit in cache, and
defeat OS readahead.

Rule: whenever a caller has a batch of article_ids to fetch (not a single one), sort the batch
by `(file_id, byte_start)` before iterating:

```python
batch = sorted(article_ids, key=lambda aid: index[aid])
```

This is free (offsets are already known from the index before any fetch happens) and turns
"random access by article" into "monotonic access with gaps" — the pattern readahead and page
cache actually handle well. It doesn't recover full sequential-scan performance, but it's a
strict improvement over unordered access at zero cost. Any caller that has visibility into a
batch of upcoming article ids (rather than being handed one id at a time with no lookahead)
should do this before fetching.

**Caveat:** no such batching caller exists in the codebase today. Every current `fetch_text`
call site is one-id-at-a-time — `MirNormalizer._is_family_sentence` fetches per-hit inside a
per-article loop, and the analysis scripts stream sentence_ids out of generators
(`Grouper.group_by_sentence`, `read_normalized_hits_tsv`). This rule is future-proofing for a
caller pattern that doesn't exist yet (e.g. reprocessing a pre-collected subset of article_ids
for retries/validation, or a parallel worker handed a pre-partitioned list of article_ids), not
a description of current behavior.

## 3. Index scope: regenerate against the filtered corpus, don't translate

The full ~450GB PMC/PubMed corpus already has a per-article byte index. `filter_corpus.py`
narrows that corpus down to articles with at least one miRNA hit, via `filter_sentences` (awk
pass) → `prepare_corpus.sh` (re-sort, optional chunking). Both steps rewrite byte offsets:

- filtering removes non-matching articles (shifting everything after them), and
- `prepare_corpus.sh` re-sorts and optionally re-splits into chunks.

So the existing full-corpus index is invalid for the filtered output — there's no cheap
adjustment for it short of replaying the same drop/keep + resort logic to recompute deltas,
which isn't meaningfully cheaper than just indexing the result directly.

**Decision: regenerate the index at filter time, against the filtered output, not the 450GB
corpus.**

- Index is always built against whatever file(s) `SentenceReader` will actually open — i.e.
  the *filtered* corpus, after `prepare_corpus.sh` produces its final output.
  - This is a linear pass over a file that's a small fraction of 450GB (only miRNA-hit
    articles survive), so the extra cost of indexing "from scratch" is small.
- `filter_corpus.py` should build the index as an added step right after `prepare_corpus.sh`
  runs (`scripts/filter_corpus.py:210`, before `cleanup`) — once per output `.sent` file if
  `--chunks > 1`. That makes the index a byproduct of the same run that produced the sentence
  file it describes, so it can never silently go stale relative to it (no separate "did I
  remember to reindex after the last filter run" bookkeeping).

## 4. Open questions / follow-ups

- Index storage format: flat TSV (`article_id\tfile_id\tbyte_start\tlength`) loaded fully
  into memory at reader construction (cheap — one row per article, not per sentence), vs. its
  own indexed-on-disk structure. Given article counts here (tens of thousands to low millions
  post-filtering), an in-memory dict is almost certainly fine and keeps this consistent with
  `SynFileReader`'s non-low-memory mode.
- Whether chunked output (`prepare_corpus.sh -n`) should get one index file per chunk or one
  combined index with `file_id` disambiguating — leaning towards one index per chunk, mirroring
  how `MultiSynFileReader` already keys everything by path.
- Where the indexing pass itself lives: a new function in `sentence_utils.py` analogous to
  `SynFileReader._index_file_fast`, invoked from `filter_corpus.py` after
  `prepare_corpus.sh` returns.
