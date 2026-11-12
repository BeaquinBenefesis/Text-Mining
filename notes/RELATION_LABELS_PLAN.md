# Relation labels (PubMedBERT): changes summary

Status: pipeline (§2), schema (§3) and UI (§7) implemented 2026-10-11 and checked on the small dev database
(`db/atlas_labels_dev.db`, from `outputs/full_labeled_run`; `scripts/web/verify_ui.py`, section "relation labels").
Not done: full run, evaluation (§6), provenance (§3), weighted next to unweighted evidence mass (§3).
Model: `PUBMEDBERT_DIR` (`resources.py`), trained on 25,752 qwen-labelled instances, test accuracy 0.791,
macro-F1 0.789 against 1000 opus-labelled instances. Notebook: `analysis/training.ipynb`.

---

## 1. Goal

The labels need a purpose that can be measured, not only displayed. Two candidates:

- **Better ranking:** down-weighting sentences that state no relation recovers more known pairs near the top
  than raw co-occurrence. Testable against HMDD (§6).
- **Correct relation types:** for genes, pairs with `targets` evidence match a curated target database better
  than pairs without. Gives `targets` an external check beyond agreement with opus.

---

## 2. Pipeline: label every co-occurrence

- **Unit:** one miRNA mention + one other entity mention in one sentence. A sentence with one miRNA and
  three genes is three instances.
- **Input must match training exactly:** tag the pair, mask all occurrences of both names (`$MIR`, `$GENE`, ...),
  prepend the entity type, cut at 320 tokens, block the labels not allowed for the type. Settings are in
  `settings.json` next to the weights.
- **Shared code:** move `mask_names` and `encode` out of the notebook into a module that the notebook and the
  pipeline both import, so training and inference cannot drift apart.
- **Output kept per evidence sentence:** all nine probabilities, not only the top label. Nothing is dropped
  in the pipeline.
- **Runtime:** estimate before the full run (number of co-occurrences, one 8 GB GPU).

---

## 3. Schema

- **Per mention pair (`mention_pair`):** the nine label probabilities, the top `label` and its `confidence`.
  One mention pair backs every association its two mentions normalise to (`association_evidence.mention_pair_id`).
- **Per association and label (`association_label`):** article count and sentence count,
  **direct evidence only** (§5).
- **`association.dominant_label`, `dominant_label_articles`:** set at build time from `association_label`
  (rule in §7). Stored so that the three list views read and filter the same value.
- **`association`:** the weighted evidence mass next to the unweighted one, so both rankings can be compared
  and the change reverted.
- **Provenance:** which model produced the labels (contents of `settings.json`), stored once per build.

---

## 4. Evidence weighting

- **Rule:** each sentence contributes `1 − P(none)` to the evidence instead of 1. This is the probability that
  the sentence states a relation; the association's evidence is the sum over its sentences.
- **Applies to the direct association and, through the existing propagation, to its parents.** The weight is
  applied before propagation.
- **No threshold, no dropping:** consistent with "all evidence is kept and ranked" (`WEIGHTED_RANKING_PLAN.md` §2).
  Low confidence in the *type* of relation does not reduce the weight; only `P(none)` does.
- **Conditional on §6:** if the weighted ranking is not better, keep `evidence_mass` unweighted and use the
  labels for display only.
- **Re-check α:** α = 2 was chosen on unweighted evidence; repeat the top-10 check once the weight is in.
- Known limit: the probabilities are overconfident, so the weight sits mostly near 0 or 1 and acts as a soft
  threshold. Temperature scaling would smooth it (§7).

---

## 5. Typed labels are not propagated

- **Evidence propagates, labels do not.** Evidence is direction-free; a label's meaning is not preserved along
  `is_a` / `part_of` edges.
  - Opposite children: `promotes` on both "positive" and "negative regulation of apoptosis" would become
    `promotes` "regulation of apoptosis".
  - Mixed directions across subtypes: the parent's dominant label would be decided by which subtype has more
    papers.
  - Mislabelled sentences from all descendants accumulate on broad terms.
- **Label counts are direct-only,** like `n_direct_articles`.
- **Associations with only propagated evidence have no label:** show "no direct evidence, see more specific
  terms", not an empty bar. The label filter excludes them; say so in the UI.

---

## 6. Evaluation

- **Ranking:** HMDD comparison with and without the `1 − P(none)` weight. Decides §4.
- **Relation type (optional):** `targets` against a curated target database.
- **Per-label trust:** re-run the evaluation cells of `analysis/training.ipynb`; its stored per-label table and
  confusion matrices come from an older run (0.760 / 0.751) and do not describe the saved model.
- Caveats to state: both label sets are model-made (qwen for training, opus for test); the rare labels have
  few test instances (`biomarker` 18, `expression_up` 23, `targets` 24); there is no validation set, so every
  choice made on the test set slightly inflates the reported score.

---

## 7. UI

### Association lists (browser)

- **Dominant label per association:** the leading *specific* label from direct evidence
  (`targets`, `inhibits`, `promotes`, `expression_up`, `expression_down`, `expressed`, `biomarker`),
  falling back to `associated`. `none` never wins.
- Ties: more sentences, then label name.
- **Shown as a chip with its support,** e.g. "inhibits 14/16" (articles with the label / direct articles).
- **Filter by label:** matches the dominant label only. "Any evidence with the label" was rejected: with
  about 1 in 5 sentences mislabelled, a well-studied association has a sentence of nearly every label.
- **The same in all three lists** (`/associations`, miRNA page, term page): shared columns, filter and
  macros (`queries._label_filter`, `_ranking.html`). The order under a filter is unchanged.
- Known limit: a specific label backed by 1 article wins over `associated` backed by 16; the support count
  shows it. Revisit on the full data.

### Association page

- **Label breakdown:** article counts per label, using each sentence's top label. An article counts
  once per label if it has at least one sentence with that label. `none` is left out of the bar and reported
  separately. Stacked bar, not a pie.
  - Alternative: sum of probabilities per label. Nearly identical here because the probabilities sit near 0 or 1,
    and harder to verify by reading the sentence list.
- **Direction as a contrast:** `promotes` vs `inhibits`, `expression_up` vs `expression_down` shown as counts
  side by side. A small minority is expected from the model's error rate (about 1 in 5) and is not presented
  as a conflict in the literature.
- **Evidence sentences:** filterable by label, sortable by confidence. A card is one sentence: it shows one
  chip per distinct label of its mention pairs and matches a filter if any pair has the label. The
  confidence order puts sentences with only `none` last.
- **Confidence display:** the ordering is reliable, the value is not. On the test set, keeping the most
  confident 70% (confidence ≥ 0.85) gives 0.903 accuracy, but the top 30% (≥ 0.983) are only 0.957 correct.
  Shown as a level: high (≥ 0.983), medium (≥ 0.85), low; the raw value is in the tooltip. Calibration
  (temperature scaling, fitted on one half of the test set and reported on the other) is still open.

---

## 8. Open

- Which associations the model cannot label besides propagated-only ones: term types outside the six trained
  types, and co-occurrences that are not within one sentence, if either exists in the database.
- Whether to calibrate the probabilities or only bin them for display.
- Check which labels survive a confidence cut-off before using one anywhere (a cut may remove the rare labels
  first).
