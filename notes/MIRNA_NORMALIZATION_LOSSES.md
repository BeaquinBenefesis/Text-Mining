# miRNA mentions lost in normalisation

Sections 1 to 4 were measured 2026-10-12 on the run `outputs/full_labeled_run` and the database built from it
(`db/atlas_labeled.db`), **before** the two fixes in §5. Section 6 is the same run repeated with the fixes
(2026-10-13, database `db/atlas_labeled_fix.db`; the run folder was overwritten in place).
Scripts: `scripts/evaluation/unknown_mirna_causes.py`, `analysis/hmdd.ipynb`.

Sections 8 to 13 (2026-10-13) compare the pipeline with HMDD: entities and relation labels, first against
the whole database, then on HMDD's own sentences (run `outputs/hmdd_sents`).

---

## 1. How the loss was found: HMDD paper coverage

HMDD v4 (`alldata_v4.txt`) cites 37,022 papers in 53,553 entries. A paper counts as held if its PMID or
its PMC id (from `pmc_metadata.csv`) is present.

| Where | HMDD papers | HMDD entries |
|---|---|---|
| In the corpus | 36,708 (99.2%) | 53,138 (99.2%) |
| In the database (at least one miRNA resolved) | 30,817 (83.2%) | 45,729 (85.4%) |
| In the database with disease evidence | 28,472 (76.9%) | 41,542 (77.6%) |

- **5,891 HMDD papers are in the corpus but have no miRNA in the database** (5,597 abstracts,
  294 PMC full texts). List: `outputs/hmdd_undetected/`.
- In 5,876 of them (99.7%) the corpus text contains a specific miRNA name such as `miR-454-3p`.
  The miRNA is found by the regular expression and then discarded by the normaliser
  (status `UNKNOWN_ENTITY`).
- Matching by PMID alone, as `analysis/hmdd.ipynb` does, gives 69.4% and undercounts: two thirds of the
  database articles are stored under PMC ids.

Note on the reference: `alldata_v4.txt` holds almost only papers with PMID above 30 million
(53,455 of 53,553 entries, roughly mid-2018 onwards). The older HMDD entries are not in this file.

---

## 2. Method

- Every miRNA row of `.norm` with status `UNKNOWN_ENTITY` was assigned to the branch of `MirNormalizer`
  that rejected it.
- The name was rebuilt from the raw text after the hit, taken from `.hits`; the article's species are
  the `TAXON` rows of `.norm`.
- All 1,640,977 unknown rows were matched to their hit.
- "Human has it" means the name exists for `hsa` in miRBase.

miRNA rows by status:

| Status | Rows |
|---|---|
| FILTERED (generic word, no name: "microRNA", "miRNAs") | 16,528,380 |
| FALLBACK | 10,496,345 |
| NORMALIZED | 8,744,880 |
| UNKNOWN_ENTITY | 1,640,977 |
| IN_BLACKLIST (ambiguous miRBase name) | 140,938 |

`UNKNOWN_ENTITY` is 7.8% of the 21.0 million mentions that carry a name.

---

## 3. Unknown mentions by cause

| Cause | Mentions | Share | Human has it | Examples |
|---|---|---|---|---|
| No species prefix, name in no species: `lin` pattern | 567,716 | 34.6% | – | `lin28`, `lin28b`, `line1`, `linc00665` |
| No species prefix, name in no species: other | 344,935 | 21.0% | – | `mir-17-92`, `mir22hg`, `mirdeep2` |
| No species prefix, name in no species: **hyphen missing** | 303,605 | 18.5% | 266,375 | `mir21`, `mir155`, `mir146a`, `let7` |
| No species prefix, **article mentions no species** | 214,434 | 13.1% | 209,953 | `mir-146a`, `mir-34a`, `mir-125b` |
| No species prefix, mentioned species lack this miRNA | 88,224 | 5.4% | 16,399 | `mir-125`, `mir-99`, `mir171` |
| No species prefix, **article mentions only species without miRNAs** | 62,080 | 3.8% | 54,727 | `mir-146a`, `mir-34a` |
| Species prefix given, no such miRNA in that species | 59,983 | 3.7% | – | `mir156`, `mir396`, `let-7` |
| **Total** | 1,640,977 | 100% | | |

- **Correctly rejected:** the `lin` rows are gene names (`LIN28`) and the word "line"; most of "other"
  are host genes (`MIR22HG`) and tool names (`miRDeep2`).
- **Real miRNAs lost for a fixable reason** (bold rows): 580,119 mentions, 35.4% of all unknown ones.
  531,055 of them exist in human.
- **Not fixed:** the cluster `miR-17-92` (22,058 mentions) and names without a letter suffix such as
  `miR-125`, which refer to several members.

---

## 4. Articles

616,100 articles have at least one miRNA hit.

| Outcome | Articles | Share |
|---|---|---|
| At least one miRNA resolved (the database articles) | 320,369 | 52.0% |
| Only generic words, no miRNA name | 158,731 | 25.8% |
| A named miRNA, none resolved | 137,000 | 22.2% |

The 137,000 articles by their most frequent cause:

| Cause | Articles |
|---|---|
| `lin` pattern | 60,312 |
| No species, or only species without miRNAs; human has the miRNA | 32,784 |
| Name in no species, other | 23,542 |
| Hyphen missing; human has the miRNA | 13,164 |
| Hyphen missing; human lacks the miRNA | 2,626 |
| Mentioned species lack this miRNA | 2,374 |
| No species, or only species without miRNAs; human lacks the miRNA | 1,371 |
| Species prefix given, no such miRNA in that species | 802 |

An article is assigned to one cause only, so these counts are approximate at the margins.

---

## 5. Fixes (in `MirNormalizer`, `src/textmining/normalization.py`)

- **Human default:** a name without a species prefix is resolved as human (`hsa`) when the article
  mentions no species that has miRNAs. Applies only where the mention would otherwise be unknown; a name
  that is also a miRBase family still resolves to the family, as before. These mentions get the status
  `FALLBACK`.
  - Reason: a miRNA paper that names no species is almost always a human study (abstracts say
    "patients" and name a cell line). HMDD makes the same assumption.
  - A species that is mentioned still takes precedence; nothing changes for those articles.
- **Hyphen fix:** `miR21` is read as `miR-21` when the fused form is not a miRBase name and the
  hyphenated form is. Plant names that miRBase itself writes fused (`zma-miR408a`) are unchanged.

Expected gain, estimated from the counts above before the re-run (measured values in §6):

| | Mentions | Articles newly in the database |
|---|---|---|
| Human default | 264,680 | about 32,800 |
| Hyphen fix | up to 303,605 | about 13,200 to 15,800 |

Together about 46,000 articles, 14% more than the 320,369 now in the database.

---

## 6. Measured effect of the fixes

Same corpus and synonym lists, full re-run with the two fixes.

| | Before | After | Change |
|---|---|---|---|
| Articles with a resolved miRNA | 320,369 | 370,890 | +50,521 (+15.8%) |
| HMDD papers in the database (of 37,022) | 30,817 (83.2%) | 36,247 (97.9%) | +5,430 |
| Co-occurrences | 49,672,556 | 51,975,550 | +2,302,994 (+4.6%) |
| Mention pairs | 17,244,173 | 18,310,996 | +1,066,823 (+6.2%) |
| Sentences with evidence | 4,144,487 | 4,415,786 | +271,299 (+6.5%) |
| Associations | 9,284,989 | 9,555,986 | +270,997 (+2.9%) |

- No article and no HMDD paper of the old database is missing from the new one.
- The estimate in §5 was 46,000 new articles; the measured gain is 50,521.
- Of the 5,891 undetected HMDD papers (§1), 461 remain.

### Unknown mentions after the fixes

The count of §3 repeated on the new run (same script, same causes).

| Cause | Before | After |
|---|---|---|
| `lin` pattern | 567,716 | 567,716 |
| Name in no species, other | 344,935 | 344,935 |
| Hyphen missing | 303,605 | 7,432 |
| Article mentions no species | 214,434 | 4,481 |
| Mentioned species lack this miRNA | 88,224 | 88,224 |
| Article mentions only species without miRNAs | 62,080 | 7,353 |
| Species prefix given, no such miRNA in that species | 59,983 | 54,738 |
| **Total `UNKNOWN_ENTITY`** | 1,640,977 | 1,074,879 |

- 566,098 mentions are recovered (34.5% of the unknown ones). The two targeted causes are almost
  empty; what remains of them are names that human does not have.
- 85% of the remaining unknown mentions are the `lin` pattern and "other" (host genes, tool names,
  clusters), which are not miRNAs or cannot be mapped to one accession.
- Articles with a named miRNA but none resolved: 137,000 before, 86,479 after; 58,796 of those are
  `lin` only.

### HMDD association coverage (`analysis/hmdd.ipynb`)

39,750 of the 53,553 HMDD entries resolve to one miRBase accession and one MONDO id.

| Found in the database | Before | After |
|---|---|---|
| Exact accession | 86.3% | 86.5% |
| Exact accession, direct evidence | 73.7% | 74.1% |
| Precursor or its mature forms | 91.6% | 91.9% |
| Precursor or its mature forms, direct evidence | 80.6% | 81.1% |

- **Pair-level coverage barely moves**, although 5,430 more HMDD papers are in the database: a pair is
  counted as found if any paper supports it, and most pairs of the recovered papers were already
  supported by another paper. The fixes add evidence to known pairs more than they add new pairs.
- The "before" column is from the notebook's stored outputs (disease mapping 39,765 resolvable entries).

Why the 5,355 resolvable entries without an exact match are missing:

| Reason | Entries |
|---|---|
| The HMDD accession is not among the miRNAs detected in that paper | 3,001 (56.0%) |
| miRNA and disease both present, pair not extracted | 1,390 (26.0%) |
| Disease term never linked to any miRNA | 811 (15.1%) |
| Paper not in the database | 102 (1.9%) |
| miRNA has no disease associations at all | 51 (1.0%) |

The first row is mostly a difference of level, not a detection failure. Of its 3,001 entries:

| What is detected in the paper | Entries |
|---|---|
| A mature form of the precursor HMDD names | 2,162 (72.0%) |
| Only other miRNAs | 660 (22.0%) |
| The family or precursor of the HMDD miRNA | 179 (6.0%) |

So "precursor or its mature forms" (91.9%) is the fair coverage figure; the exact-accession figure
penalises the pipeline for resolving `miR-21-5p` where HMDD writes `hsa-mir-21`.

Papers are matched by PMID or PMC id. With PMID only, as the notebook did before, 32.6% of the missing
entries were attributed to "paper not in corpus"; the correct share is 1.9%.

---

## 7. Open (normalisation)

- **Risk of the human default:** a non-human study that never names its organism is now attributed to
  human. Check a sample of the `FALLBACK` mentions that come from the default.
- **`lin` pattern:** it produces a third of all unknown mentions. They are rejected correctly, but the
  pattern should not match "line" and `LINC…` in the first place.
- **Clusters and member-less names** (`miR-17-92`, `miR-125`): decide how to represent them.
- **Pairs not extracted although both entities are in the paper** (1,390 entries): not examined; likely
  the miRNA and the disease never share a sentence.
- **Disease mapping:** 23% of HMDD entries are lost on the disease name; map through MeSH ids.
- **Complete HMDD reference:** add the entries from before 2018 (§1).

---

# Comparison with HMDD

## 8. What is compared

HMDD v4 (`alldata_v4.txt`): 53,553 entries. One entry is a miRNA name, a disease name, a PMID, a code
(23 different) and a description (a sentence or a few sentences from the paper).

Two comparisons were made:

| | A. Whole database | B. HMDD's own sentences |
|---|---|---|
| Text used on my side | all corpus articles (`db/atlas_labeled_fix.db`) | only HMDD's descriptions (`outputs/hmdd_sents`) |
| Question | are HMDD's pairs in the database, and with which label | does the pipeline find HMDD's miRNA, disease and relation in the sentence HMDD quotes |
| Unit | one HMDD entry | one HMDD entry |

### Mapping HMDD names to identifiers (both comparisons, `analysis/hmdd.ipynb`)

- **miRNA:** the name is looked up in miRBase as precursor, then as mature form, first as written and then
  ignoring case. If neither matches, the species prefix is removed and the rest is looked up as a family,
  accepted only if that family has a member in the named species. Ambiguous names are not used.
  51,627 entries get one accession.
- **Disease:** the name is compared with the MONDO synonyms after lower-casing and replacing hyphens and
  slashes by spaces; then without a plural "s"; then with the comma inversion undone
  ("Carcinoma, Hepatocellular" to "hepatocellular carcinoma"). A name matching several MONDO terms is not
  used. 41,099 entries get one MONDO id.
- **Usable entries:** 39,750 have both identifiers.

### Mapping HMDD codes to labels (both comparisons)

Only 12 of the 23 codes say something about the miRNA-disease relation:

| HMDD code | Labels counted as agreement |
|---|---|
| `genetics_overexpression_promote`, `genetics_knock down_suppress` | promotes |
| `genetics_overexpression_suppress`, `genetics_knock down_promote` | inhibits |
| `tissue_expression_up` / `_down` | expression_up / expression_down |
| `circulation_biomarker_diagnosis_ns`, `..._prognosis_ns` | biomarker |
| `circulation_biomarker_..._up` | biomarker, expression_up |
| `circulation_biomarker_..._down` | biomarker, expression_down |

The other codes (`other`, `lncRNA target`, `target gene`, `exosome`, ...) are not compared.

### One label per entry (both comparisons)

An entry usually matches several labelled mention pairs. They are reduced to one **leading label**: the
most frequent specific label; `associated` only if there is no specific one; `none` only if there is nothing
else. Two measures per entry:

- **leading agrees:** the leading label is one of the labels allowed for the HMDD code;
- **any agrees:** at least one of the matching pairs has an allowed label.

---

## 9. Comparison A: whole database

### Method

- **Paper coverage:** an HMDD paper is in the database if its PMID or its PMC id (`pmc_metadata.csv`) is an
  article there.
- **Association coverage:** an HMDD entry is found if the database has an association between its miRNA and
  exactly its MONDO term, in any paper. Counted twice: with HMDD's exact accession, and with the accession
  or the mature forms of that precursor.
- **Label agreement, paper level:** for each entry with a mapped code, take the evidence sentences for the
  miRNA (accession or mature forms) with exactly the MONDO term, **only from the paper HMDD cites**. Their
  labels give the leading label.
- **Label agreement, pair level:** the same, using the evidence from **all papers** for that pair.

### Results

Coverage (details in §1 and §6):

| | Share |
|---|---|
| HMDD papers in the database | 97.9% (36,247 of 37,022) |
| HMDD pairs in the database, exact accession | 86.5% |
| HMDD pairs in the database, precursor or mature forms | 91.9% |
| the same, with direct (sentence) evidence | 81.1% |

Label agreement, paper level. 11,294 entries have a mapped code and both identifiers; 5,165 of them have
evidence in the cited paper.

| HMDD label | n | Leading agrees |
|---|---|---|
| expression_up | 32 | 72% |
| biomarker | 2,433 | 56% |
| expression_down | 31 | 55% |
| inhibits | 1,152 | 50% |
| promotes | 1,517 | 20% |
| **All** | 5,165 | 44.1% (any agrees: 60.8%) |

- Pair level: leading agrees 34.4%, any agrees 78.7%.
- For biomarker entries the leading label is `biomarker` in 45%, `expression_up` in 18% and
  `expression_down` in 12%.
- The four genetics codes give the same distribution of my labels (`inhibits` 45 to 60%, `promotes`
  9 to 29%), whatever direction the code names.

### Limits of comparison A

- My evidence sentences are not the sentence HMDD quotes; a paper says several things about one pair.
- An HMDD code describes the paper's finding; my label describes single sentences.

Comparison B removes the first limit.

---

## 10. Comparison B: HMDD's own sentences

### Method

1. **Sentence file.** `HMDD/extract_sents.py` writes every distinct (PMID, description) as one "sentence"
   with the id `PMID.n.n` (39,163 lines) and keeps the link to the entries in `associations_key.tsv`
   (53,553 rows). Checked: every key row points to its own text.
2. **Pipeline.** The miRNA-disease pipeline is run on that file unchanged: syngrep, normalisation,
   co-occurrence, relation labels. Each PMID is treated as an article that consists of its descriptions only.
3. **miRNA recovered:** the description yields HMDD's accession, or a mature form or precursor of it, or its
   family.
4. **Disease recovered:** the description yields HMDD's MONDO term, or one of its ancestors (broader), or
   one of its descendants (more specific).
5. **Pair recovered:** a co-occurrence in that description joins a recovered miRNA with a recovered disease.
6. **Label:** the labels of those co-occurrences give the leading label (§8), compared with the HMDD code.

About 10% of the descriptions hold more than one sentence; they are treated as one.

### Run

| | Count |
|---|---|
| Descriptions | 39,163 |
| with a resolved miRNA | 25,589 (65.3%) |
| with a resolved disease | 14,425 (36.8%) |
| with a miRNA-disease co-occurrence | 10,752 (27.5%) |
| Co-occurrences, all labelled | 29,334 |

### Entities recovered

miRNA (51,627 entries with one accession):

| Found in the description | Entries | Share |
|---|---|---|
| HMDD's exact accession | 13,354 | 25.9% |
| Its mature form or precursor | 5,559 | 10.8% |
| Its family | 11,746 | 22.8% |
| Only another miRNA | 4,353 | 8.4% |
| No miRNA resolved | 16,615 | 32.2% |

Disease (41,099 entries with one MONDO id):

| Found in the description | Entries | Share |
|---|---|---|
| HMDD's exact term | 6,225 | 15.1% |
| A more specific term | 4,778 | 11.6% |
| A broader term | 2,454 | 6.0% |
| Only another disease | 2,244 | 5.5% |
| No disease found | 25,398 | 61.8% |

Pair (39,750 entries with both ids): **9,006 recovered (22.7%)**. Where both entities are recovered, the
pair is extracted in 99.2% of the entries.

---

## 11. Why entities are missing in comparison B

### miRNA (20,968 entries: "only another miRNA" and "no miRNA resolved")

Method: test whether the number of HMDD's miRNA ("224" for `hsa-mir-224`) occurs in the description. A
description counts as damaged if it ends in "miR"/"miRNA"/"microRNA", starts with "3p"/"5p", or contains
"miR3p"/"miR5p".

| Reason | Entries | Share |
|---|---|---|
| Number not in the text, text damaged | 16,388 | 78.2% |
| Number not in the text, no visible damage | 2,867 | 13.7% |
| Number in the text, resolved to a different miRNA | 980 | 4.7% |
| Number in the text, name rejected by the normaliser | 367 | 1.8% |
| Number in the text, only a generic word matched | 333 | 1.6% |
| Number in the text, no miRNA pattern matched | 33 | 0.2% |

- **HMDD's text is damaged.** Descriptions are cut inside a miRNA name ("...could promote OA through miR",
  "5p overexpression weakened...") or a number is deleted ("miR-15a-5p and miR5p"). About 14,700 entries
  (27%) match the damage patterns. The Excel version of HMDD shows the same damage.
- **HMDD's miRNA column is damaged too:** `hsa-mir-30` for a sentence on miR-330, `hsa-mir-662` for
  miR-3662, `hsa-mir-1` for miR-21. Not counted.
- **Pipeline misses** are about 8% (1,700 entries): lists and clusters ("miR-19a-19b-20a"), "microRNA
  218-5p" with a space, "exomiR-1246", and rat or mouse studies resolved to `rno-`/`mmu-`.
- The damage patterns are a test, not a verified count: cut sentences of other forms are missed
  ("positive BC.", "miR3383p").

Family instead of precursor (22.8%) is not a loss: a name without species prefix resolves to the family
when the text names no species, and only 3,808 descriptions name one.

### Disease (27,642 entries: "only another disease" and "no disease found")

Method: look at the raw syngrep matches before any filtering (`.hits`) and compare them with what is kept
(`.norm`).

| Reason | Entries | Share |
|---|---|---|
| No disease name or abbreviation matched at all | 14,678 | 53.1% |
| HMDD's disease matched as an abbreviation, then dropped | 7,186 | 26.0% |
| Only an abbreviation of another term matched and dropped | 5,778 | 20.9% |

- **Abbreviations need context.** The pipeline keeps an abbreviation only if the article supports it.
  Here an article is one sentence: of 19,361 abbreviation matches, 106 are kept. Most frequent dropped ones:
  HCC, NSCLC, CRC, ESCC, NPC, AML.
- The third row is mostly the words "was" and "can" matching an abbreviation; correctly dropped.
- **"Nothing matched", read by hand** (30 random descriptions): 17 name the disease by an abbreviation
  that is not in the synonym list (OS, BC, AP, OA, AMI, IgAN, GDM); 10 name no disease (9 of them cut
  text); 3 spell it out differently from HMDD. Small sample.

List of all missed sentences: `outputs/hmdd_sents/missed_diseases.tsv` (21,354 rows, one per sentence and
HMDD disease; columns for the dropped abbreviation and its position, what was found instead, and the
damage flag).

| Category in the file | Intact text | Damaged text |
|---|---|---|
| Abbreviation in the list, dropped | 4,103 | 1,799 |
| Another disease found | 1,176 | 340 |
| Nothing matched | 8,016 | 5,920 |

This is not a recall measurement: HMDD's disease describes the paper, and it is not known for every
sentence whether the disease is written in it.

---

## 12. Label comparison on HMDD's sentences

Of the 9,006 recovered entries, **2,097** have a code that maps to a label (§8). File:
`outputs/hmdd_sents/label_comparison.tsv`.

Besides the exact agreement, a coarse one was computed, **same kind of relation**: a causal label
(`promotes` or `inhibits`) for genetics codes; `biomarker`, `expression_up` or `expression_down` for
circulation codes; `expression_up` or `expression_down` for tissue codes.

| HMDD group | n | Same kind | Exact (leading agrees) |
|---|---|---|---|
| Genetics | 1,077 | 74.1% | 30.2% |
| Circulation | 998 | 53.9% | 41.2% |
| Tissue | 22 | 45.5% | 40.9% |
| **All** | 2,097 | 64.2% | 35.5% |

Exact agreement by HMDD label: biomarker 41.2% (n=998), inhibits 44.9% (405), promotes 21.3% (672),
expression_down 54.5% (11), expression_up 27.3% (11). By model confidence: high 40.4%, medium 33.0%,
low 33.2%.

My leading label per genetics code (row %):

| HMDD code | n | inhibits | promotes | associated | other |
|---|---|---|---|---|---|
| `genetics_overexpression_promote` | 553 | 59 | 18 | 7 | 16 |
| `genetics_knock down_promote` | 280 | 38 | 38 | 11 | 13 |
| `genetics_overexpression_suppress` | 125 | 60 | 7 | 10 | 23 |
| `genetics_knock down_suppress` | 119 | 28 | 37 | 18 | 17 |

### Checks on HMDD's codes

- **Keyword test.** Share of sentences with a word for inhibition (suppress, inhibit, reduce, decrease,
  repress, attenuate, impair), per genetics code: 62%, 63%, 69%, 71%. The two "promote" codes do not differ
  from the two "suppress" codes, so the code does not follow the direction stated in the sentence.
- **Reading.** 12 random high-confidence entries coded `genetics_overexpression_promote` and labelled
  `inhibits` by the model: in all 12 the sentence says the miRNA inhibits ("Overexpression of miR-383
  suppressed cell proliferation ... in hepatocellular carcinoma").
- **Code fit.** Share of sentences that contain the word their code names: `circRNA target` 86%,
  `exosome` 84%, but `lncRNA target` 11% and `transcription factor target` 2%. Part of the code column
  does not describe its sentence.
- **Biomarker entries labelled `none`** (8 read): sentences that describe a measurement, not a finding
  ("...recruited to measure miR-29b ... in whole blood").

---

## 13. Conclusion

- **Coverage is high where the pipeline has the article.** 97.9% of HMDD's papers and 91.9% of its
  miRNA-disease pairs are in the database (81.1% with sentence evidence).
- **On HMDD's isolated sentences only 22.7% of the pairs are recovered.** The main causes are outside the
  extraction method: damaged text in HMDD (about 27% of entries, 78% of the miRNA misses) and disease
  abbreviations that cannot be resolved without the rest of the article (26% of the disease misses).
  A real limit remains: disease abbreviations missing from the synonym list.
- **Co-occurrence extraction loses almost nothing:** 99.2% of the entries with both entities yield the pair.
- **Label agreement with HMDD is low in both comparisons** (exact: 44.1% at paper level, 35.5% on HMDD's
  sentences). The kind of relation agrees more often (64.2%; 74.1% for genetics codes).
- **HMDD's codes are not a usable ground truth for the direction of an effect.** The same result appears in
  both comparisons (same label distribution under all four genetics codes), the keyword test shows the codes
  do not follow the sentence, and in the sentences read the model was right.
- **Consequence:** HMDD supports statements about coverage and about the kind of relation. The accuracy of
  the relation classifier has to be taken from the hand-labelled test set.

### Open (HMDD comparison)

- Download HMDD again and check whether the damaged text and the code column are the same in the release.
- Disease recall: hand-annotate about 100 corpus sentences.
- The reading samples are small (12, 8 and 30 sentences); enlarge them before quoting the pattern as a rate.
- 4,103 intact sentences have a dropped abbreviation at a known position; accepting those that agree with
  HMDD's disease would enlarge the label sample.
- Abbreviations missing from the disease list (AMI, OS, BC, OA, ...).
