# Hit group disambiguation: proposed logic

Status: proposed 2026-09-14, not implemented.
Replaces the body of `HitProcessor._resolve_groups` (`src/textmining/hit_utils.py`).
Implements decision 1 of `DATABASE_DESIGN_NOTES.txt` §13.4: a mention matched by
several entity types produces one hit per type instead of being dropped.

---

## 1. Context: what happens before resolution

`HitProcessor.create_article` runs, per article:

1. `_group_hits_by_span`: hits with exactly the same span form one `HitGroup`.
2. `_drop_contained_groups`: a group whose span lies inside another group's span is dropped.
3. `_collect_article_evidence`: `unambiguous_entity_ids` = ids of groups that have
   one id and whose first hit is not an `ABBREVIATION`.
4. `_resolve_groups`: this document.

Evidence (step 3) is collected **before** resolution and is not changed by this
proposal. A group that only resolves through the new multi-type path does not add
to the evidence.

Terminology:

- **standard hit**: from a normal synonym file (`disease.syn`, `cl.syn`, ...)
- **abbreviation hit** (`ABBREVIATION`): from an `*_abbreviations.syn` file
- **inferred abbreviation hit** (`INFERRED_ABBREVIATION`): produced by syngrep's
  abbreviation mode from an in-text definition such as "... (EMT)"
- **supported id**: an id in `unambiguous_entity_ids`

---

## 2. What is wrong with the current logic

| # | Problem | Consequence |
|---|---|---|
| P1 | A group whose surviving hits span several types ends in `AMBIGUOUS_ENTITY_TYPE` and is dropped. | 186,991 groups lost in the 2026-09-08 run, concentrated on high-value terms (Wnt signaling pathway 29,728). |
| P2 | The cross-type `supported_ids` check runs before the type check, so one supported id picks a **type**. | The same string yields different types depending on unrelated mentions in the article. |
| P3 | The type set is read from `g.hits`, not from the filtered hits. | Hits removed by the abbreviation filter still count as a type. Two TAXON ids plus an unsupported DISEASE abbreviation is dropped as `AMBIGUOUS_ENTITY_TYPE`, although the survivors are one type that LCA could resolve. |
| P4 | The comment in the inferred-abbreviation branch says "keep only the inferred abbreviations". | The code keeps every non-`ABBREVIATION` hit, standard hits of other types included. The comment overstates what the filter does. |

---

## 3. Proposed flow

### 3.1 Group level (per `HitGroup`)

```
resolve_group(g, evidence):

  # Step 1: fast path (unchanged)
  if g has one id and no abbreviation hit:
      status = EXACT_MATCH; emit g.first; return

  # Step 2: abbreviation filter on the WHOLE group (unchanged logic)
  if g contains an inferred abbreviation:
      hits = [h in g.hits if h is not ABBREVIATION]
  elif g contains an abbreviation:
      hits = [h in g.hits if h is not ABBREVIATION or h.id is supported]
  else:
      hits = g.hits

  # Step 3: contextual miRNA preference on the WHOLE group (unchanged)
  hits = prefer_contextual_mir(hits)

  # Step 4: nothing left (unchanged)
  if hits is empty:
      status = FAILURE; return

  # Step 5: one surviving id (unchanged). Necessarily one type.
  if distinct ids of hits == 1:
      status = RESOLVED; emit that hit; return

  # From here on, everything is computed from `hits`, never `g.hits`  (fixes P3)
  types = distinct entity types of hits

  # Step 6: single type
  if len(types) == 1:
      hit, status = resolve_single_type(hits, evidence)
      emit hit if resolved; return

  # Step 7: MIR exception (current behaviour kept for miRNA collisions)
  if MIR in types:
      supported = ids of hits ∩ evidence
      if len(supported) == 1:
          status = RESOLVED; emit the supported hit
      else:
          status = AMBIGUOUS_ENTITY_TYPE
      return

  # Step 8: several non-MIR types -> split and resolve each part  (fixes P1, P2)
  parts = partition hits by entity type          # every part is non-empty
  results = [resolve_single_type(part, evidence) for part in parts]
  resolved = [hit for hit, ok in results if ok]
  emit all resolved
  status = RESOLVED_MULTI_TYPE   if all parts resolved
           PARTIALLY_RESOLVED    if some parts resolved
           AMBIGUOUS_ID          if none resolved
  debug log: types accepted / types present, ids per type
```

### 3.2 Type level

Extracted from the existing per-type branch (`hit_utils.py:183-217`). Used by
step 6 and step 8, so the same code resolves single-type and multi-type groups.

```
resolve_single_type(hits, evidence) -> (hit | None, status):
  ids = distinct ids of hits                     # all hits share one entity type

  if len(ids) == 1:
      return that hit, RESOLVED

  supported = ids ∩ evidence
  if len(supported) == 1:
      return the supported hit, RESOLVED

  ontology = type_to_ontology[type]
  if ontology is missing:
      warn; return None, AMBIGUOUS_ID

  lca = ontology.find_lca(*ids)
  if lca is None:
      return None, AMBIGUOUS_ID
  return copy of a template hit with entity_id = lca, RESOLVED
```

---

## 4. Design choices and why

### 4.1 Split instead of dropping (P1)
A string such as "Wnt signaling pathway" is correctly both a pathway (PW) and a
biological process (GO). Cell types are in both CL and BTO because BTO's own scope
is "tissues, cell types and enzyme sources" (`BTO:0000000`). Picking one owner would
need hand-curated tables that every ontology release can invalidate, which blocks
an automated `refresh_data.py`. The precision cost is accepted and stated in the
methods (see §6).

### 4.2 Abbreviation filter before the split
The filter uses evidence that spans types. If an article defines
"Parkinson's disease (PD)", that definition should suppress abbreviation readings of
"PD" from every type, not only DISEASE. Filtering per part would let the CL part
ignore the definition.

### 4.3 `_prefer_contextual_mir` before the split
It decides between a miRNA reading and anything else. That decision is cross-type
by nature.

### 4.4 The one-id check stays before the split
If only one id survives filtering, only one type survives, and there is nothing to
split. This path covers the ordinary standard-vs-abbreviation case: for "pig" the
DISEASE abbreviation is unsupported, only TAXON survives, and the group resolves as
it does today.

### 4.5 The support check moves into the per-type helper (P2)
Article support should choose **among ids of one type**, never **between types**.
Otherwise the same mention gives PW+GO in one article and GO only in the next,
depending on whether a GO-only synonym happens to appear elsewhere.

### 4.6 Types and parts come from the filtered hits (P3)
Hits removed in steps 2-3 must not create a type or a part. Consequence: every part
has at least one hit, so "empty part" cannot occur and does not need handling.

### 4.7 MIR groups are not split
Every association hangs off a miRNA. A false miRNA hit (e.g. "bantam" the chicken
breed, without miRNA context) costs more than a false term hit. When a MIR hit
survives the contextual preference alongside other types, keep today's behaviour.
`AMBIGUOUS_ENTITY_TYPE` therefore now means only "a miRNA without miRNA context
collides with another type".

### 4.8 Partial resolution emits the resolved parts
Ambiguity among GO ids says nothing about whether the PW reading is correct.
Dropping a correctly resolved part because another type is ambiguous would lose
information for no gain in precision.

---

## 5. Statuses and counting

### 5.1 `GroupStatus`

| Status | Meaning | Emits |
|---|---|---|
| `EXACT_MATCH` | one id, no abbreviation | 1 |
| `RESOLVED` | one type resolved (steps 5, 6, or 7 with support) | 1 |
| `RESOLVED_MULTI_TYPE` **(new)** | split, every part resolved | ≥ 2 |
| `PARTIALLY_RESOLVED` **(new)** | split, some parts resolved, some `AMBIGUOUS_ID` | ≥ 1 |
| `AMBIGUOUS_ID` | nothing resolved (single type, or every part failed) | 0 |
| `AMBIGUOUS_ENTITY_TYPE` | MIR collision without support (step 7) | 0 |
| `FAILURE` | nothing survived the filters | 0 |

### 5.2 History
- `record_group` keeps counting by status. Count `RESOLVED_MULTI_TYPE` and
  `PARTIALLY_RESOLVED` as resolved when computing the resolution rate
  (currently resolved groups / all groups, 76.68% in the full run).
- Output hits can now exceed resolved groups. Add a counter of **hits emitted per
  group** (1, 2, 3, ...). That is the number the methods need: how often one
  mention backs associations in more than one facet.
- Per-synonym lists ("Top 10 ... unresolved") treat `PARTIALLY_RESOLVED` as
  resolved, and should gain a list for it so ambiguous parts stay visible.
- The debug line in step 8 is for development only; debug logging is usually off
  in full runs and is not aggregated.

---

## 6. Constraints this creates (state them in the methods)

1. **No score may sum associations across term types.** One mention can back
   (miR-21, PW:Wnt) and (miR-21, GO:Wnt). Scoring per (miRNA, term) and propagation
   within one ontology are unaffected; any cross-type aggregate is not.
2. **Cell types appear in both the CELL and TISSUE facets.** Mitigated by a
   computed "also a CL term" flag on TISSUE entities (§13.4 decision 2), not by
   exclusion.
3. **Downstream sanity:** split hits share a span. `ENTITIES_PER_SENTENCE_CAP` counts
   distinct spans and `Grouper` only pairs MIR with non-MIR hits, so neither is
   inflated.

---

## 7. Worked examples

| Case | Hits after steps 2-3 | Path | Result |
|---|---|---|---|
| "Wnt signaling pathway", no support | PW:a, GO:b | step 8 | `RESOLVED_MULTI_TYPE`, 2 hits |
| same, GO-only synonym elsewhere in article | PW:a, GO:b (b supported) | step 8 | `RESOLVED_MULTI_TYPE`, 2 hits. Today: GO only (P2) |
| "hepatocyte" | CL:a, TISSUE:b | step 8 | `RESOLVED_MULTI_TYPE`, 2 hits; TISSUE entity flagged |
| "pig", disease abbreviation unsupported | TAXON:a | step 5 | `RESOLVED` (unchanged) |
| "PD", no definition, acronym rule applied (both sides `ABBREVIATION`) | none | step 4 | `FAILURE`. Today: CL pyloric dilator neuron |
| "PD" with "Parkinson's disease (PD)" in the article | inferred DISEASE hit | step 5 | `RESOLVED` to the disease |
| two TAXON ids + unsupported DISEASE abbreviation | TAXON:a, TAXON:b | step 6 → LCA | `RESOLVED`. Today: `AMBIGUOUS_ENTITY_TYPE` (P3) |
| PW:a + GO:b + GO:c, GO ids without LCA | PW:a, GO:b, GO:c | step 8 | `PARTIALLY_RESOLVED`, PW hit only |
| "bantam", no miRNA context | MIR:a, TAXON:b | step 7 | `AMBIGUOUS_ENTITY_TYPE` (unchanged) |
| "let-7 ...", miRNA context | MIR:a | step 5 | `RESOLVED` (unchanged) |

The "PD" rows assume decision 3 of §13.4 (acronym shape heuristic) is implemented;
without it, CL's "PD" is a standard hit and still wins in the first "PD" row.

---

## 8. Consequence of the root restriction for LCA

After restricting graphs to their roots (§13.1), DISEASE, CELL, PATHWAY and GO-BP
each have one root, so `find_lca` always finds a common ancestor. In practice
`AMBIGUOUS_ID` from a missing LCA will almost disappear for these types and be
replaced by hits resolved to very general terms, up to the root itself. TISSUE (two
roots) can still fail. This is intended: those hits are removed later by the
normalised-IC threshold (§13.1), not by resolution. Expect the share of
LCA-resolved hits on general terms to rise; report it.

---

## 9. Tests to write

Unit tests on `_resolve_groups` with hand-built groups and evidence, one per row of
§7, plus:

- a group with one abbreviation hit and support → `RESOLVED`; without support → `FAILURE`
- MIR + TAXON with the TAXON id supported → `RESOLVED` to TAXON (step 7)
- multi-type group where every part fails → `AMBIGUOUS_ID`, nothing emitted
- a type without a configured ontology inside a split group → that part `AMBIGUOUS_ID`,
  the other parts still emitted
- emitted hits of a split group keep their own `entity_type` and `entity_id`, and the
  same span
- the history counts the new statuses and the hits-per-group distribution

---

## 10. Open questions

1. **LCA over all ids or over supported ids.** When two or more ids of one type are
   supported, the helper (like today's code) takes the LCA over **all** ids. Taking it
   over the supported ids only would be more specific. Not changed here.
2. **Inferred-abbreviation filter scope (P4).** The filter keeps standard hits of other
   types. With the acronym heuristic this matters less; decide whether an in-text
   definition should also suppress **standard** short synonyms of other types.
3. **Resolution rate definition.** Whether `PARTIALLY_RESOLVED` counts as resolved in
   the reported rate (proposed: yes, with the hits-per-group counter reported alongside).
