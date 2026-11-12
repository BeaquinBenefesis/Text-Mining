# IC threshold: choosing the cutoff for uninformative ontology terms

Status: **in progress, paused 2026-09-15.** Round 2 own labels 19 / 329 done.
Relates to `DATABASE_DESIGN_NOTES.txt` §13.1, §14.3, §14.4 (where the cutoff is applied)
and §16 (decisions of record from this analysis).

> **Blinding warning.** Sections 5 and 6 contain the LLM raters' round 2 results.
> Reading them before finishing the round 2 labels biases those labels.
> Label from `outputs/ic_threshold_term_annotated/round2/items.tsv` first. Do not open
> `round2_agents/`, `round2_key/` or `comparison.tsv` until then.

---

## 1. Question and definitions

Uninformative general terms (*disease*, *cell*, *biological_process*) are removed at DB load
by a threshold on normalised structural IC (§14.4). This document is about **choosing
the value** of that threshold.

- **IC** (`OntologyGraph.compute_ic_from_index`): `IC = −ln(c / N)`.
  - `c` is the term's descendant count + 1.
  - `N` is the number of nodes in the restricted graph.
- **Normalised IC:** `IC_norm = IC / ln N = 1 − ln c / ln N`, in [0, 1].
  - `IC_norm < t` is equivalent to `c > N^(1−t)`.
  - So the same `t` is not the same rule in every ontology, and small ontologies need a
    relatively broader term before it is cut.
- **Annotation question:** *"If the knowledgebase reported 'miR-X is associated with ⟨term⟩',
  would that narrow down the biological context enough to be worth a miRNA researcher's
  attention?"*
- **Scale:** 0 uninformative / 1 borderline / 2 informative.
  - Judge **generality only**: not plausibility, not extraction correctness, not
    whether the term is well-formed in its ontology.
- **Cutoff target (decided):** separates **0 from ≥ 1**. The filter applied at load time
  removes only what is clearly uninformative.

## 2. Decisions so far

| # | Decision |
|---|---|
| R1 | **Monotonicity.** A term never scores above any of its descendants (all ontologies). Checked automatically after every labelling round, for every rater. |
| R2 | **Grouping classes.** Union classes ("X or Y"), "… by …" classes, and classes without direct mentions whose descendant set is almost that of one child score no higher than that child. |
| R3 | **Neoplasm cluster = 1 / 1 / 1 / 1** (*cancer or benign tumor*, *neoplastic disease or syndrome*, *neoplasm*, *cancer*). 55% of miRNAs with any disease association are directly associated with *cancer* or *neoplasm*, so neither narrows the context beyond "tumour-related". Cleaner evidence was deliberately not used as an argument. |
| — | Cutoff separates 0 from ≥ 1. |
| — | Noise on general terms (fixed phrases like "tumor suppressor", abbreviations falling back to the lowest common ancestor) is a separate problem, logged as open in §16.3. The IC threshold is not the tool for it. |
| — | Round 2 scope, stopping rule and procedure fixed before labelling (§16.4). |

Rejected along the way:
- stratified random sampling: too few terms per band, so label all of them instead;
- per-ontology quantile cutoffs;
- corpus "promiscuity" (how many miRNAs a term associates with) as a filter: circular, and it removes well-studied specific terms;
- Haiku as a rater (§4).

## 3. Method

1. **Term lists.** `scripts/exploration/ic_threshold_terms.py` writes all terms with IC_norm < t, cumulative, to `outputs/ic_threshold_terms/` for t ∈ {0.05 … 0.30, 0.40, 0.45, 0.50}. It uses the restricted graphs: MONDO, GO-BP, CL, PW over is_a; BTO over is_a + part_of.
2. **Own labels.**
   - Round 1: from the name-sorted term list, v1 then v2.
   - Round 2: from a shuffled blind file with name and definition.
3. **LLM raters.**
   - Fresh agents with no project context.
   - Input: only a shuffled file with ontology, name and OBO definition.
   - No IC, no hierarchy, no access to own labels.
   - Same prompt in both rounds. It does **not** include R1–R3.
4. **Agreement.**
   - Exact agreement.
   - Cohen's κ, and linear-weighted κ for the 3-level scale.
   - Binary κ for 0 vs ≥ 1.
5. **Cutoff estimates.**
   - *Crossover:* logistic fit `P(score ≥ 1) ~ IC_norm` per ontology and rater. The cutoff is where P = 0.5, with a bootstrap 95% CI (1000 resamples).
   - *Floor:* the highest IC below which no term was rated ≥ 1.
6. **Hierarchy check.** Count ancestor–descendant pairs within the labelled set where the ancestor is scored higher.

## 4. Round 1: 106 terms with IC_norm < 0.30

Composition: MONDO 41, GO-BP 30, CL 17, PW 7, BTO 11.

**Score distributions**

| rater | 0 | 1 | 2 |
|---|---|---|---|
| own v1 | 64 | 31 | 11 |
| own v2 | 62 | 35 | 9 |
| Opus | 74 | 31 | 1 |
| Sonnet | 77 | 23 | 6 |
| Haiku | 40 | 28 | 38 |

**Agreement**

| pair | exact | κ | κ_w |
|---|---|---|---|
| v1 vs v2 | 0.85 | 0.72 | 0.77 |
| Opus vs Sonnet | 0.83 | 0.60 | 0.64 |
| v1 vs Opus / Sonnet | 0.77 / 0.75 | 0.54 / 0.48 | 0.57 / 0.56 |
| v2 vs Opus / Sonnet | 0.75 / 0.74 | 0.48 / 0.47 | 0.49 / 0.52 |
| Haiku vs Opus / Sonnet | 0.43 / 0.48 | 0.14 / 0.20 | 0.26 / 0.30 |

**Hierarchy violations** (of 292 ancestor–descendant pairs): v1 4, v2 4, Opus 0, Sonnet 1, Haiku 13.

Findings:
- **Haiku is unusable** and was dropped from round 2.
- **Own labels are more lenient than Opus/Sonnet, and v2 moved away from them:** 11 of 16 changes increased the distance to the agent median.
- **CELL disagrees most** (exact agreement 0.47). The disputed terms are functional grouping classes: *electrically active / responsive / signaling cell*, *motile cell*, *secretory cell*.
- **GO-BP and PW below 0.30:** almost everything is 0 for every rater.
- **MONDO organ-system disorders at 0.26–0.30** split about 50/50 for every rater.
- **Own hierarchy violations:**
  - *localization* / *establishment of localization* (1) > *transport* (0), in v1 and v2;
  - *cancer or benign tumor* (2) > *neoplasm* (1), in v2 (resolved by R3);
  - *nervous system disorder* > *hereditary neurological disease* and *urogenital system* > *reproductive system*, in v1.

**Still open from round 1** (not yet re-labelled under R1–R3):
- CELL functional grouping classes;
- organ-system disorders (*eye disorder* 1 vs *disorder of visual system* 0 vs *disorder of orbital region* 0);
- the *transport* / *localization* violation;
- cross-ontology consistency (*brain* / *brain disorder* / *CNS neuron*);
- non-human-animal duplicate classes.

## 5. Round 2: 329 new terms, agents only (own labels pending)

**Scope:** all ontologies 0.30 ≤ IC_norm < 0.40; GO-BP and PW also up to 0.50.
GO-BP 190, DISEASE 53, PW 34, CELL 30, TISSUE 22.

**Score distributions:** Opus 220 / 102 / 7, Sonnet 190 / 118 / 21 (0 / 1 / 2).

### 5.1 Agreement Opus vs Sonnet (round 2)

| | n | κ_w (3-level) | binary exact | binary κ |
|---|---|---|---|---|
| all | 329 | 0.68 | 0.87 | 0.73 |
| DISEASE | 53 | 0.71 | 0.91 | 0.80 |
| GO-BP | 190 | 0.63 | 0.89 | 0.63 |
| CELL | 30 | 0.51 | 0.83 | 0.57 |
| TISSUE | 22 | 0.50 | 0.86 | 0.59 |
| PATHWAY | 34 | 0.48 | 0.74 | 0.50 |

### 5.2 Share rated ≥ 1 per 0.05 band (rounds 1 + 2 combined; Opus / Sonnet)

| band | DISEASE | CELL | TISSUE | PATHWAY | GO-BP |
|---|---|---|---|---|---|
| < 0.15 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| 0.15–0.20 | .25 / .25 (n4) | .50 / .50 (n6) | 0 / 0 (n1) | 0 / 1 (n1) | 0 / 0 (n1) |
| 0.20–0.25 | .50 / .33 (n6) | .33 / .33 (n6) | .50 / .75 (n4) | 0 / 0 (n3) | 0 / 0 (n7) |
| 0.25–0.30 | .73 / .55 (n22) | 1 / 1 (n2) | .40 / .20 (n5) | 1 / 1 (n1) | 0 / .06 (n17) |
| 0.30–0.35 | .44 / .61 (n18) | .30 / .70 (n10) | .83 / .83 (n6) | 0 / .17 (n6) | 0 / 0 (n16) |
| 0.35–0.40 | .66 / .71 (n35) | .85 / .90 (n20) | .69 / .88 (n16) | 0 / .60 (n5) | .03 / .03 (n38) |
| 0.40–0.45 | — | — | — | .64 / .82 (n11) | .12 / .15 (n59) |
| 0.45–0.50 | — | — | — | .50 / .75 (n12) | .27 / .35 (n77) |

**Stopping rule** (two consecutive bands with ≥ 80% rated ≥ 1): **not met** for any
ontology or rater, except TISSUE for Sonnet (from 0.30).

### 5.3 Crossover: IC_norm where half the terms are rated ≥ 1

| ontology | Opus | Sonnet | inside labelled range? |
|---|---|---|---|
| CELL | 0.26 [0.18, 0.32] | 0.23 [0.17, 0.28] | yes |
| TISSUE | 0.28 [0.13, 0.35] | 0.26 [0.14, 0.31] | yes, wide CI |
| DISEASE | 0.28 [0.22, 0.33] | 0.29 [0.25, 0.33] | yes |
| PATHWAY | 0.46 [0.41, 0.57] | 0.35 [0.26, 0.42] | yes, but the raters disagree |
| GO-BP | 0.53 [0.50, 0.59] | 0.50 [0.48, 0.55] | **no**, at or above the top of the range |

### 5.4 Floor: highest cutoff that removes nothing rated informative

- **Strict:** every term below is 0 for both agents.
- **Lenient:** every term below is 0 for at least one agent.

| ontology | strict | removed | first "yes" (Opus/Sonnet) | lenient | removed | first "yes" by both |
|---|---|---|---|---|---|---|
| DISEASE | 0.169 | 9 | nervous system disorder (1/1) | 0.169 | 9 | same |
| CELL | 0.171 | 5 | neuron (1/2) | 0.171 | 5 | same |
| TISSUE | 0.213 | 2 | nervous system (0/1) | 0.243 | 3 | central nervous system (1/1) |
| PATHWAY | 0.199 | 2 | classic metabolic pathway (0/1) | 0.299 | 6 | cardiovascular system drug pathway (1/1) |
| GO-BP | 0.297 | 29 | nucleobase-containing compound metabolic process (0/1) | 0.370 | 56 | lipid metabolic process (1/1) |

A single term sets each floor, so floors are fragile. Read them as "no lower than this".

### 5.5 Hierarchy violations (rounds 1 + 2, ancestor ≥ 1 while descendant 0)

Opus 8 (CELL 4: *epithelial cell* > its subtypes; DISEASE 3; TISSUE 1), Sonnet 13 (GO-BP 11:
*nucleobase-containing compound metabolic process* > *DNA metabolic process* etc.; DISEASE 1; TISSUE 1).
Blind raters cannot enforce R1, so apply the check to them as well.

## 6. Interpretation (provisional: agents only)

Summary:

| ontology | floor (no informative term lost) | crossover (half informative) |
|---|---|---|
| DISEASE | 0.17 | ~0.28 |
| CELL | 0.17 | ~0.25 |
| TISSUE | 0.21–0.24 | ~0.27 |
| PATHWAY | 0.20–0.30 | 0.35–0.46 |
| GO-BP | 0.30–0.37 | ~0.50+ |

1. **A single global cutoff does not fit.**
   - MONDO, CL and BTO cross over at about 0.23–0.29; GO-BP at about 0.50 or higher.
   - At 0.28, GO-BP terms that are almost all 0 are kept.
   - At 0.50, about 2/3 informative DISEASE terms in 0.35–0.40 are removed.
   - Even GO-BP's conservative floor (0.30–0.37) is above the DISEASE/CELL crossover.
   - Likely cause: GO-BP is large and deep, with long "regulation of …" chains, so its structural IC rises slowly.
   - **The evidence favours per-ontology cutoffs**, or at least a separate GO-BP cutoff.
2. **GO-BP is not covered yet.** Its crossover sits at the top of the labelled range, so the estimate extrapolates. PATHWAY is uncertain because the raters disagree.
3. **The stopping rule may never be met.** Grouping classes occur at every IC level, so the informative share may level off below 80%. Changing the rule now would be post-hoc: document it as such and report both versions.
4. **Floor vs. crossover fits the two-threshold design.**
   - The floor is a safe **load-time** filter: it deletes nothing any rater calls informative.
   - The crossover is a candidate **UI default** filter: stricter, adjustable, deletes nothing.

Caveats:
- two LLM raters and no own round 2 labels yet;
- LLM raters are a consistency check, not ground truth;
- CELL, TISSUE and PW have only 33–47 terms each;
- IC comes from today's graphs, not a rerun build.

## 7. Next steps

1. **Finish the round 2 own labels** (310 left), blind. Keep R1–R3 in mind. Add a `note` column for hard cases.
   - *lipid metabolic process* and *cardiovascular system drug pathway* were named in §5.4. If they weren't labelled before reading this, consider excluding them.
2. **Re-run the comparison** including own labels. Extend `analysis_scripts/round2_analysis.py` with an `own` rater, per-band shares, crossover, floor and the R1 check.
3. **Re-label the disputed round-1 terms** under R1–R3, as a v3 of the disputed items only.
4. **Decide round 3:** GO-BP (and PW?) from 0.50 to about 0.65. Count the terms first.
5. **Decide the stopping rule** (keep, or amend post-hoc and document).
6. **Decide global vs. per-ontology cutoffs**, then record the floor (load time) and crossover (UI default) values in §14.4 and in build provenance.
7. **Open, separate from the threshold** (§16.3):
   - the "tumor suppressor" / "tumor necrosis factor" phrases;
   - an IC floor on fallback to the lowest common ancestor;
   - a mention-precision sample (neoplasm, cancer, HCC, cell, pathway).
8. **Re-state R3's 55% figure** from the rerun for human mature miRNAs.

## 8. Files

All under `outputs/ic_threshold_term_annotated/`. `outputs/` is **gitignored**, so none of this is versioned.

| path | content |
|---|---|
| `terms_ic_below_0.30.v1.tsv`, `.v2.tsv` | own round 1 labels (term name and score separated by spaces, not a tab) |
| `terms_ic_below_0.30.{opus,sonnet,haiku}.tsv` | round 1 agent labels + rationale, joined to term IDs |
| `comparison.tsv` | round 1, all raters + IC_norm (**not blind**) |
| `round1_blind/` | round 1 agent input (`items.tsv`, seed 20260915), `key.tsv`, raw agent scores |
| `round2/items.tsv` | **own round 2 labelling file** (seed 20260916) |
| `round2_key/key.tsv` | item_id → term_id (**do not open before labelling is done**) |
| `round2_agents/` | agent input copy without scores, raw agent scores, scores joined to term IDs, `comparison_agents.tsv` (**not blind**) |
| `analysis_scripts/compare.py` | round 1 comparison: distributions, pairwise κ, per ontology, v1→v2 changes |
| `analysis_scripts/round2_analysis.py` | round 2: agreement, bands, stopping rule, crossover + CI, hierarchy check |
| `analysis_scripts/modifier_use.py` | noise analysis: surface forms and next-word phrases per term (`python modifier_use.py MONDO_0005070 …`) |
| `analysis_scripts/ic_counts.py` | counts of associated terms and their ancestors below cutoffs (old `full_run.assoc`) |

The scripts are quick one-offs. Run them from the repo root with the project venv. Move them to
`scripts/exploration/` if they should be versioned.

| `analysis_scripts/corpus_idf.py` | propagated article frequency per term (Resnik corpus IC) → `corpus_df.pkl` |
| `corpus_df.pkl` | `{n_articles, direct, prop}`; `prop[entity_type][accession]` = articles mentioning the term **or any descendant** |

---

## 9. Weighted ranking instead of a display cutoff (2026-09-16)

### 9.1 The idea

Rather than deleting low-IC terms, rank by evidence **and** specificity at once, so vague
terms sink on their own. Tested on hsa-miR-21-5p (atlas.db 2026-09-11), top 500 per facet.

Schemes: `score × IC_norm`; geometric mean of min–max normalised score and IC;
mean rank / rank fusion; Pareto front (skyline).

### 9.2 Result: `score × IC_norm` wins

Sorted by raw score, **every facet has a vacuous term at rank 1**: *neoplasm* (0.19|10.3),
*disease* (0.00|10.0), *signaling* (0.55|9.8), *cell* (0.00|10.8), *pathway* (0.00|9.9).
Weighting removes all of them with no threshold: IC = 0 at the root forces the product to 0,
the same argument as §5.3's propagation decay.

The weighted DISEASE and CELL lists read like a real miR-21 profile: diabetic kidney disease,
COVID-19, HCC, type 1 diabetes, renal fibrosis; M2 macrophage, platelet, Treg, podocyte.
Both are documented miR-21 biology (kidney fibrosis, M2 polarisation).

Rejected variants:
- **Rank fusion / mean rank.** IC has huge tie mass at exactly 1.00 (every leaf), so rank
  averaging is decided by that tie group: *bone resorption* (score 5.1) outranks HCC (8.6).
- **Pareto front.** Always contains the top-scoring term however vacuous — the DISEASE layer 1
  is *neoplasm*, *cancer*, *colorectal cancer*, HCC, *diabetic kidney disease*, only 5 items.
- **Geometric mean.** Nearly identical ordering to the plain product; extra normalisation
  parameter buys nothing.

Spearman(score, IC_norm) over the top 500: DISEASE −0.23, GO-BP −0.11, CELL −0.21,
PATHWAY −0.67. Weakly negative is the good case (criteria near-independent). PATHWAY is
degenerate anyway (22 associations; *pathway* and *signaling pathway* hold 704 and 348
articles, the rest 3–29) — do not tune on PW before the rerun.

**Side effects to handle:**
- **Thin evidence floats up:** *endothelial colony forming cell* (5 articles),
  *glycolysis pathway* (1), *blastema* (1). A minimum-article guard is required.
- **Specificity amplifies method artifacts:** *reverse transcription* (IC 0.89, 128 articles)
  tops the weighted GO list — RT-qPCR in methods sections. Needs §16.3 noise work, not ranking.
- TISSUE unusable in this build: 8 of miR-21's 12 tissue terms are stale BTO ids
  (*animal*, *cell culture*, *coculture*, …), see §13.2.

### 9.3 Corpus IDF (TF-IDF idea) — computed, rejected as a ranking weight

`idf_norm(term) = log2(A / df(term)) / log2(A)`, with `df` = articles mentioning the term
**or any descendant** (propagation is essential; without it the measure is inverted, since
vague terms are rarely written out). A = 320,963 articles. This is Resnik corpus IC and is
what §8.3 calls `ic_corpus`. Cost: 16 s from atlas.db.

| term | IC_norm | articles | share | idf_norm |
|---|---|---|---|---|
| disease | 0.00 | 221,076 | 68.9% | 0.03 |
| neoplasm | 0.19 | 151,180 | 47.1% | 0.06 |
| cancer | 0.25 | 132,211 | 41.2% | 0.07 |
| breast cancer | 0.56 | 30,845 | 9.6% | 0.18 |
| hepatocellular carcinoma | 0.76 | 23,446 | 7.3% | 0.21 |
| cellular process | 0.09 | 141,621 | 44.1% | 0.06 |
| reverse transcription | 0.89 | 12,203 | 3.8% | 0.26 |
| apoptotic process | 0.58 | 2,124 | 0.7% | 0.40 |

**AUC for "both agents call the term informative"** (rounds 1+2 labels):

| ontology | n | IC_norm | idf | both features |
|---|---|---|---|---|
| GO-BP | 220 | **0.78** | 0.63 | 0.78 |
| CELL | 47 | **0.80** | 0.67 | 0.76 |
| DISEASE | 92 | 0.71 | 0.45 | **0.81** |
| PATHWAY | 26 | **0.76** | 0.41 | 0.78 |
| pooled | 391 | 0.50 | 0.44 | 0.60 |

- IDF is **worse than structural IC in every ontology**, and at chance for DISEASE (0.45):
  *breast cancer* is specific but appears in 9.6% of articles, so IDF calls it uninformative.
- It does **not** fix cross-ontology comparability (pooled 0.44 / 0.60), which was the hope.
- As a ranking weight it makes miR-21 lists worse: `score × IDF` tops GO-BP with
  *osteoclast differentiation*, *bone resorption*, *sperm capacitation*; DISEASE with
  *myasthenia gravis*, *vitiligo*, *scrapie*. `score × IC × IDF` double-counts specificity
  (ρ(IC, idf) = +0.41 … +0.65) and squeezes the evidence out.
- It does **not** suppress *reverse transcription* (3.8% of articles → idf 0.26, above
  angiogenesis at 0.23).

### 9.4 Decisions

1. **UI ranking: `score × IC_norm`** (normalised structural IC). Implementation started 2026-09-16.
2. **Don't store `ic_corpus` either** (revised 2026-09-16). An unused column costs a loader,
   validation and UI surface for nothing. The prototype script stays as methods material
   (*cancer* 41%, *disease* 69% of articles). Revisit only for a DISEASE-only two-feature cutoff.
3. **Never feed corpus IDF into propagation decay** (it is itself computed from propagated
   counts — feedback loop).
4. **Minimum-article guard** alongside any weighting; pick the value against HMDD (≈10 articles
   is the order of magnitude these lists suggest).
5. **The load-time floor is still needed**: §14.3's ~10% of file size on root-level terms, and
   weighting alone never removes those rows from the DB.
6. **A hard display cutoff is no longer needed** — weighting replaces it. The annotation only
   has to justify the conservative floor (IC ≈ 0.17), where raters agree.

### 9.5 Implementation notes for the weighted score

- Keep `association.score` as it is (evidence amount). Weight at **query time**: keep the
  ablations comparable and make re-tuning a query change, not a 16-minute rebuild.
- Needs `entity.ic` (normalised structural IC; §14.6 planned it as `ic_structural`): IC / ln N per term, computed once at
  build from the same restricted graph as the closure, recorded with roots + relationships.
- Roots get IC = 0, so `score × IC_norm` = 0 — they vanish from ranked lists automatically.
- Offer raw-score sorting in the UI too; the weighted order is a default, not a truth.
- Evaluate with recall@k against HMDD, plain score vs weighted, plus a manual top-10 review for
  a handful of miRNAs. Caveat: HMDD is disease-only and cancer-heavy, which favours raw score.
