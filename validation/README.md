# Validation (deprecated, currently unusable)

`disease_validation.py` was written for an older version of the package and does not run:
it imports `HitsProcessor` (now `HitProcessor`) and uses the `src.textmining` import prefix.
Input preparation for the NCBI disease corpus is in `scripts/pubtator.py`.
Kept for future rework.
