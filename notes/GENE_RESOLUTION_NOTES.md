# Gene resolution in HitProcessor

`HitProcessor` no longer holds the ontologies. It receives one `GroupResolver` per entity type, built by the type's config (`EntityConfig.get_resolver`), and asks it for three things: the canonical form of an id read from a synonym file (`canonical_id`), the id together with its ancestors (`lineage`), and which of several same-type ids at one span to keep (`resolve`). Ontology-backed types use `LcaResolver`, which keeps the previous behaviour: a single id or an id supported elsewhere in the article is taken directly, otherwise the lowest common ancestor is emitted. miRNA has no resolver, so its ids pass through unchanged and are settled by the normalizer. `resolve` returns a list of hits, because one span can now yield more than one hit.

Genes use `GeneResolver`, which chooses by organism instead of by ontology. The gene-to-organism map is loaded by `GeneConfig` and translated to taxon ids. For each article, `HitProcessor` collects the taxon ids of all taxon-only groups together with their ancestors (`ArticleEvidence.taxon_ids`), so that a strain or subspecies counts as its species and an ambiguous word such as "mice" (*Mus musculus* or *Mus sp.*) still counts as mouse. A gene name shared by several organisms is kept for those organisms that the article mentions, one hit per organism, provided each of them has exactly one id for that name. If none of the organisms is mentioned, the group stays `AMBIGUOUS_ID`, unless `GeneConfig.default_taxon` is set and is among the candidates. A gene name with a single id is emitted without an organism check (`EXACT_MATCH`).

| Article contains | Gene name shared by | Emitted |
|---|---|---|
| human | human, mouse, rat | human |
| "mice" (ambiguous taxon) | human, mouse, rat | mouse |
| a mouse subspecies | human, mouse, rat | mouse |
| human and mouse | human, mouse, rat | human and mouse |
| zebrafish only | human, mouse, rat | nothing (`AMBIGUOUS_ID`); human if `default_taxon` is human |
| no taxon | human, mouse, rat | nothing (`AMBIGUOUS_ID`); human if `default_taxon` is human |
| bovine | two bovine ids | nothing (`AMBIGUOUS_ID`) |
| zebrafish only | mouse only | mouse (`EXACT_MATCH`, no organism check) |

The examples come from a synthetic run of `HitProcessor` against the real gene and taxon dictionaries.
