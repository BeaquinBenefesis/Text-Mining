"""Count the miRNA mentions that end as UNKNOWN_ENTITY by cause (notes/MIRNA_NORMALIZATION_LOSSES.md).

Replays the branches of MirNormalizer as they were before the human default and the
hyphen fix: the raw text around each hit comes from .hits, the article's species from .norm.

    RUN=outputs/<run>/<run>; WORK=<scratch dir>
    LC_ALL=C awk -F'\t' -v OFS='\t' '$3=="MIR"||$3=="TAXON"{print $1,$2,$3,$6,$8,$13}' $RUN.norm > $WORK/norm_mir_taxon.tsv
    LC_ALL=C grep -P '\t0:[0-9]+\t' $RUN.hits > $WORK/hits_mir.tsv      # 0: is the miRNA synonym file
    python scripts/evaluation/unknown_mirna_causes.py $WORK
"""
import sys
from collections import Counter
from itertools import groupby

sys.path.insert(0, "src")
from textmining.config import MirbaseResources
from textmining.normalization import MirIdMapper, MirNormalizer
from textmining.normalization_resources import MirResourceLoader

S = sys.argv[1]
m = MirbaseResources()
res = MirResourceLoader.load(
    mirna_taxons_path=m.mirna_taxons_path, mirna_2_prefix_path=m.mirna_to_prefix_path,
    family_normalizer_path=m.family_norm_path, precursor_normalizer_path=m.precursor_norm_path,
    mature_normalizer_path=m.mature_norm_path, precursor_ambiguous_path=m.precursor_ambi_path,
    mature_ambiguous_path=m.mature_ambi_path)
normalizer = MirNormalizer(res)
RESOLVED = {"NORMALIZED", "FALLBACK", "ARM_FALLBACK", "IN_BLACKLIST"}


def norm_articles():
    def rows():
        with open(f"{S}/norm_mir_taxon.tsv", encoding="utf8", errors="replace") as f:
            for line in f:
                sid, chunk, kind, entity_id, start, status = line.rstrip("\n").split("\t")
                yield (chunk, sid.split(".", 1)[0]), sid, kind, entity_id, start, status
    for key, group in groupby(rows(), key=lambda r: r[0]):
        yield key, list(group)


def hit_articles():
    def rows():
        with open(f"{S}/hits_mir.tsv", encoding="utf8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                chunk, sid = parts[0].split(":", 1)
                yield (chunk, sid.split(".", 1)[0]), sid, parts[3], parts[6], parts[7]
    for key, group in groupby(rows(), key=lambda r: r[0]):
        yield key, {(sid, start): (prefix, suffix) for _, sid, start, prefix, suffix in group}


def cause(entity_id, prefix, suffix, taxa):
    prefix = normalizer.normalize_prefix(prefix.lower())
    suffix = normalizer.normalize_suffix(suffix.lower())
    name = MirIdMapper.resolve_token(entity_id) + (suffix or "")
    species = res.mirna_2_prefix.get(name)
    human = "human has it" if species and "hsa" in species else "human lacks it"
    if prefix:
        return ("A prefix given, no such miRNA in that species", "exists in other species" if species else "name in no species"), name
    if not species:
        body = MirIdMapper.resolve_token(entity_id)
        rest = name[len(body):]
        hyphenated = res.mirna_2_prefix.get(body + "-" + rest) if rest and rest[0] != "-" else None
        if hyphenated:
            kind = "hyphen missing, human has it" if "hsa" in hyphenated else "hyphen missing, human lacks it"
        elif body == "lin":
            kind = "lin... (gene names, 'line')"
        else:
            kind = "other"
        return ("B no prefix, name in no species", kind), name
    implied = {res.taxon_2_prefix[t] for t in taxa if t in res.taxon_2_prefix}
    if not taxa:
        return ("C no prefix, article mentions no species", human), name
    if not implied:
        return ("D no prefix, article mentions only species without miRNAs", human), name
    if not implied & species:
        return ("E no prefix, mentioned species lack this miRNA", human), name
    return ("F prefix inferred, name ambiguous or unmapped", human), name


mentions, statuses, names = Counter(), Counter(), {}
articles = Counter()
unmatched = hit_only = 0
hits = hit_articles()
for key, rows in norm_articles():
    mirs = [r for r in rows if r[2] == "MIR"]
    if not mirs:
        continue
    # articles whose miRNA hits were all dropped before normalisation are in .hits only
    hit_key, by_position = next(hits)
    skipped = 0
    while hit_key != key:
        hit_key, by_position = next(hits)
        skipped += 1
        hit_only += 1
        if skipped > 10_000:
            raise SystemExit(f"files not in the same article order at {key}")
    taxa = {r[3] for r in rows if r[2] == "TAXON"}
    article_causes, resolved = Counter(), False
    for _, sid, _, entity_id, start, status in mirs:
        statuses[status] += 1
        if status in RESOLVED:
            resolved = True
        if status != "UNKNOWN_ENTITY":
            continue
        if (sid, start) not in by_position:
            unmatched += 1
            continue
        c, name = cause(entity_id, *by_position[(sid, start)], taxa)
        mentions[c] += 1
        article_causes[c] += 1
        names.setdefault(c if c[0][0] == 'B' else c[0], Counter())[name] += 1
    named = any(r[5] != "FILTERED" for r in mirs)
    if not named:
        articles["only generic mentions (filtered)"] += 1
    elif resolved:
        articles["at least one miRNA resolved"] += 1
    else:
        articles[("no miRNA resolved", *article_causes.most_common(1)[0][0])] += 1

total_unknown = statuses["UNKNOWN_ENTITY"]
print("miRNA rows by status:", dict(statuses))
print(f"UNKNOWN_ENTITY rows: {total_unknown:,}  (not found in .hits: {unmatched:,})\n")
print(f"articles with miRNA hits in .hits but no miRNA row in .norm: {hit_only:,}")
print("mentions by cause")
for c, n in sorted(mentions.items()):
    print(f"  {n:10,} {100 * n / total_unknown:5.1f}%  {c[0]} | {c[1]}")
print("\nmost frequent names per cause")
for c in sorted(names, key=str):
    print(f"  {c}: " + ", ".join(f"{name} ({n:,})" for name, n in names[c].most_common(12)))
print("\narticles with a miRNA hit:", f"{sum(articles.values()):,}")
for c, n in sorted(articles.items(), key=lambda kv: str(kv[0])):
    print(f"  {n:10,} {100 * n / sum(articles.values()):5.1f}%  {c}")
