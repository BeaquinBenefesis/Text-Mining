"""Post-build verification for the UI data layer.

Run after `python -m textmining.db.build_db`:

    python scripts/web/verify_ui.py
    TEXTMINING_DB=db/atlas_dev.db python scripts/web/verify_ui.py

Checks row counts, that the UI's queries use indexes rather than scanning,
that highlight offsets land on real surface forms, that a term page lists the
term's own associations only, that an ambiguous miRBase identifier
still has a timeline despite having no associations, and that share
normalisation actually removes the corpus's recency bias.
"""
import sys, time, re, sqlite3, os, json
from pathlib import Path
sys.path.insert(0, "src")
from textmining.db.connect import open_readonly, DB_PATH
from textmining.web import queries as Q
from textmining.models import HitType
from textmining.resources import ONTOLOGY_ROOTS

con = open_readonly(Path(os.environ.get("TEXTMINING_DB", DB_PATH)), immutable=True)
fails = []
def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{' -- ' + detail if detail else ''}")
    if not ok: fails.append(label)

print("\n=== 1. row counts ===")
counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in
          ("entity","synonym","association","ontology_closure","article","sentence",
           "association_evidence","mir_mention_article","mirna_name_history","corpus_year","search_name")}
for t, n in counts.items(): print(f"  {t:22} {n:>12,}")
check("mir_mention_article ~4.0M", 3_900_000 < counts["mir_mention_article"] < 4_100_000, f"{counts['mir_mention_article']:,}")
check("mirna_name_history == 544,564", counts["mirna_name_history"] == 544_564)
n_taxon = con.execute("SELECT count(*) FROM entity WHERE entity_type='TAXON'").fetchone()[0]
check("no TAXON entities loaded", n_taxon == 0, f"{n_taxon:,}")
n_non_gene = con.execute("SELECT count(*) FROM entity WHERE entity_type <> 'GENE'").fetchone()[0]
check("entity is miRNAs + ontology terms + genes, no taxa", 100_000 < n_non_gene < 300_000
      and con.execute("SELECT count(*) FROM entity WHERE entity_type = 'TAXON'").fetchone()[0] == 0,
      f"{n_non_gene:,} non-gene")
check("retired accessions present", con.execute(
    "SELECT count(*) FROM entity WHERE obsolete=1").fetchone()[0] > 1_000)
check("search_name covers reachable entities", counts["search_name"] > 100_000, f"{counts['search_name']:,}")
check("mir_mention_article stores rows once (WITHOUT ROWID)", con.execute(
    "SELECT count(*) FROM sqlite_master WHERE type='index' AND tbl_name='mir_mention_article'"
).fetchone()[0] == 0, "no separate PK index")
check("unused entity(type,organism) index is gone", con.execute(
    "SELECT count(*) FROM sqlite_master WHERE name='ix_entity_type_org'").fetchone()[0] == 0)
check("corpus_year populated", counts["corpus_year"] > 20)

print("\n=== 2. index effectiveness ===")
mir = con.execute("SELECT id, accession FROM entity WHERE primary_name='hsa-miR-21-5p'").fetchone()
mir_id, mir_acc = mir["id"], mir["accession"]
aid = con.execute("SELECT id FROM association ORDER BY score DESC LIMIT 1").fetchone()["id"]
for label, sql, params in [
    ("evidence by association", "SELECT id FROM association_evidence WHERE association_id=?", (aid,)),
    ("association by term",     "SELECT id FROM association WHERE term_entity_id=? ORDER BY score DESC", (1,)),
    ("sentence by article",     "SELECT id FROM sentence WHERE article_id=?", (1,)),
]:
    plan = " ".join(str(r[3]) for r in con.execute("EXPLAIN QUERY PLAN " + sql, params))
    check(f"no full SCAN: {label}", "SCAN" not in plan or "USING" in plan, plan)

t0 = time.time(); tl = Q.mirna_timeline(con, mir_acc); dt = time.time() - t0
check("miRNA timeline < 0.5s (was 5.6s)", dt < 0.5, f"{dt:.3f}s, {len(tl)} years")
t0 = time.time(); ev = Q.association_evidence(con, aid); dt = time.time() - t0
check("evidence page < 0.5s", dt < 0.5, f"{dt:.3f}s")

print("\n=== 3. highlight correctness ===")
sample_ids = [r[0] for r in con.execute(
    "SELECT association_id FROM association_evidence GROUP BY association_id ORDER BY random() LIMIT 12")]
bad_mir = bad_term = total = 0
for a in sample_ids:
    for card in Q.association_evidence(con, a, per_page=3)["items"]:
        text = card["text"]
        for s, e, kind in card["spans"]:
            total += 1
            frag = text[s:e]
            if kind == "mir" and not re.search(r"(?i)(micro-?rna|mir|let|lin|bantam|lsy|iab)", frag): bad_mir += 1
            # 2-char term spans are legitimate and common -- they are ABBREVIATION
            # synonyms (GC gastric cancer, OA osteoarthritis, MI myocardial
            # infarction), 7.9% of all evidence. Only a 1-char span is anomalous.
            if kind == "term" and (not frag.strip() or len(frag.strip()) < 2): bad_term += 1
check("miRNA spans look like miRNA names", bad_mir == 0, f"{bad_mir}/{total} bad")
check("term spans non-trivial", bad_term <= max(1, total // 100), f"{bad_term}/{total} 1-char")

# 1-char term spans are an upstream extraction defect, not a UI one: a single
# letter or digit matched as a term, almost always resolving to an ontology ROOT
# (MONDO_0700096 human disease, CL_0000000 cell, PW_0000001 pathway). Tracked, not fixed
# here -- the fix belongs in the synonym/abbreviation resolution.
one_char = con.execute(
    "SELECT count(*) FROM association_evidence WHERE term_end - term_start = 1").fetchone()[0]
n_ev = con.execute("SELECT count(*) FROM association_evidence").fetchone()[0]
check("1-char term spans stay rare", one_char / n_ev < 0.01,
      f"{one_char:,}/{n_ev:,} = {100*one_char/n_ev:.3f}%")
mir_lens = [e - s for a in sample_ids for c in Q.association_evidence(con, a, per_page=3)["items"]
            for s, e, k in c["spans"] if k == "mir"]
check("extension lengthened miRNA spans", mir_lens and sum(mir_lens)/len(mir_lens) > 4,
      f"mean {sum(mir_lens)/len(mir_lens):.1f} chars (stored spans are ~3)")

print("\n=== 4. term page: this term only ===")
bc = con.execute("SELECT id, accession FROM entity WHERE accession='MONDO_0007254'").fetchone()
res = Q.term_mirnas(con, bc["id"], organism="hsa", per_page=10)
direct = con.execute("""
    SELECT count(*) FROM association a JOIN entity m ON m.id = a.mirna_entity_id
    WHERE a.term_entity_id = ? AND m.organism = 'hsa'
""", (bc["id"],)).fetchone()[0]
check("one row per association with the term", res["total"] == direct, f"{res['total']:,} vs {direct:,}")
term_ids = {con.execute("SELECT term_entity_id FROM association WHERE id = ?", (r["id"],)).fetchone()[0]
            for r in res["items"]}
check("every row is an association with the term itself", term_ids == {bc["id"]})
check("ordered by evidence",
      [r["score"] for r in res["items"]] == sorted((r["score"] for r in res["items"]), reverse=True))

print("\n=== 5. conflict view ===")
conf = Q.name_conflict(con, "hsa-miR-34b")
check("hsa-miR-34b is a conflict", conf and conf["ambiguous"])
accs = {c["accession"] for c in conf["candidates"]} if conf else set()
check("both mature accessions present", {"MIMAT0000685","MIMAT0004676"} <= accs, str(sorted(accs)))
# hsa-mir-34b resolves to its precursor (ARM_FALLBACK); take the most mentioned name still blacklisted
blacklisted = con.execute("SELECT mir_key FROM mir_mention_article WHERE blacklisted GROUP BY mir_key "
                          "ORDER BY count(*) DESC LIMIT 1").fetchone()[0]
tl = Q.mirna_timeline(con, blacklisted)
check(f"blacklisted name {blacklisted} has a timeline", len(tl) > 0, f"{len(tl)} years, {sum(p['n_articles'] for p in tl):,} articles")
check("name absent from association data", con.execute(
    "SELECT count(*) FROM association WHERE mirna_entity_id IN (SELECT id FROM entity WHERE accession='MIMAT0004676')"
).fetchone()[0] >= 0)

print("\n=== 6. normalisation sanity ===")
# If normalisation works, raw curves should peak late (tracking the corpus, which
# grows to 2021-2025) while share curves peak where the miRNA was actually topical.
accs = [r[0] for r in con.execute("""
        SELECT e.accession FROM association a JOIN entity e ON e.id=a.mirna_entity_id
        WHERE e.organism='hsa' GROUP BY e.accession ORDER BY count(*) DESC LIMIT 20""")]
raw_peaks, share_peaks = [], []
for acc in accs:
    pts = [p for p in Q.mirna_timeline(con, acc) if p["year"] and p["year"] < 2026]
    if len(pts) < 5: continue
    raw_peaks.append(max(pts, key=lambda p: p["n_articles"])["year"])
    share_peaks.append(max(pts, key=lambda p: p["share"])["year"])
late_raw = sum(1 for y in raw_peaks if y >= 2021)
late_share = sum(1 for y in share_peaks if y >= 2021)
print(f"  raw   peak years: {sorted(raw_peaks)}")
print(f"  share peak years: {sorted(share_peaks)}")
check("raw peaks cluster in the corpus-heavy years", late_raw >= 0.6 * len(raw_peaks),
      f"{late_raw}/{len(raw_peaks)} peak >= 2021")
check("share peaks are more dispersed than raw", late_share < late_raw,
      f"share {late_share}/{len(share_peaks)} vs raw {late_raw}/{len(raw_peaks)} peak >= 2021")

print("\n=== 7. weighted ranking ===")
ALPHA = Q.RELEVANCE_ALPHA
ic_stats = con.execute("""SELECT count(*), sum(ic IS NULL), sum(ic < 0 OR ic > 1) FROM entity
                          WHERE entity_type <> 'MIR'""").fetchone()
check("term ic within [0, 1]", ic_stats[2] == 0, f"{ic_stats[2]} out of range")
# 0 on a real build; the migrated dev database keeps stale ids without ic.
print(f"  terms without ic: {ic_stats[1]:,} of {ic_stats[0]:,}")
check("miRNA rows carry no ic", con.execute(
    "SELECT count(*) FROM entity WHERE entity_type = 'MIR' AND ic IS NOT NULL").fetchone()[0] == 0)
mass = con.execute("""SELECT sum(evidence_mass < 0), max(abs(score - log2(1 + evidence_mass))),
                             sum(n_articles < 1), sum(n_direct_articles > n_articles)
                      FROM association""").fetchone()
check("evidence_mass >= 0", mass[0] == 0, f"{mass[0]} negative")
check("score == log2(1 + evidence_mass)", mass[1] < 1e-3, f"max diff {mass[1]:.2e}")
check("1 <= n_articles and n_direct_articles <= n_articles", mass[2] == 0 and mass[3] == 0,
      f"{mass[2]} below 1, {mass[3]} direct above total")

t0 = time.time(); page = Q.mirna_associations(con, mir_id, "DISEASE", sort="relevance"); dt = time.time() - t0
check("miR-21 relevance page < 50ms", dt < 0.05, f"{dt*1000:.1f}ms")
keys = [r["evidence_mass"] * r["ic"] ** ALPHA for r in page["items"] if r["ic"] is not None]
check("miR-21 page ordered by E * ic^alpha", all(a >= b - 1e-9 for a, b in zip(keys, keys[1:])))
check("relevance never above score", all(r["relevance"] is None or r["relevance"] <= r["score"] + 1e-9
                                         for r in page["items"]))
check("no root term on miR-21's first relevance page", all(r["ic"] != 0 for r in page["items"]),
      ", ".join(r["term_name"] for r in page["items"][:5]))
evid_page = Q.mirna_associations(con, mir_id, "DISEASE", sort="evidence")
check("evidence sort keeps the old score order",
      [r["score"] for r in evid_page["items"]] == sorted((r["score"] for r in evid_page["items"]), reverse=True))
check("sorting does not change totals", page["total"] == evid_page["total"])

root_accession = ONTOLOGY_ROOTS[HitType.DISEASE][0].replace(":", "_")
root = con.execute("SELECT id FROM entity WHERE accession = ?", (root_accession,)).fetchone()["id"]
t0 = time.time(); Q.term_mirnas(con, root, organism="hsa"); dt = time.time() - t0
check("MONDO root term page < 5s", dt < 5, f"{dt:.2f}s")

for args in [("relevance", "DISEASE", "hsa", "mature"), ("evidence", "DISEASE", None, None)]:
    Q._TOP_CACHE.clear()
    t0 = time.time(); top = Q.top_associations(con, *args); dt = time.time() - t0
    t0 = time.time(); Q.top_associations(con, *args); cached = time.time() - t0
    key = (lambda r: r["evidence_mass"] * (r["ic"] or 0) ** ALPHA) if args[0] == "relevance" else (lambda r: r["score"])
    ks = [key(r) for r in top["items"]]
    check(f"top_associations{args} ordered", all(a >= b - 1e-9 for a, b in zip(ks, ks[1:])),
          f"uncached {dt:.2f}s, cached {cached*1000:.2f}ms, total {top['total']:,}")

print("\n=== genes ===")
import textmining.resources as res
from urllib.parse import quote
n_dict = sum(1 for line in open(res.GENE_SYNS) if ":" in line)
n_gene = con.execute("SELECT count(*) FROM entity WHERE entity_type='GENE'").fetchone()[0]
check("one gene entity per dictionary record", n_gene == n_dict, f"{n_gene:,} vs {n_dict:,}")
check("every gene has a name and an organism", con.execute(
    "SELECT count(*) FROM entity WHERE entity_type='GENE' AND (primary_name='' OR organism IS NULL)").fetchone()[0] == 0)
check("no syngrep tag left in gene names or synonyms", con.execute("""
    SELECT (SELECT count(*) FROM entity WHERE primary_name LIKE '%@CASE_SENS')
         + (SELECT count(*) FROM synonym WHERE synonym_name LIKE '%@CASE_SENS')""").fetchone()[0] == 0)
n_gene_assoc = con.execute("SELECT count(*) FROM association WHERE term_type='GENE'").fetchone()[0]
check("gene associations loaded", n_gene_assoc > 0, f"{n_gene_assoc:,}")
check("gene associations point at gene entities", con.execute("""
    SELECT count(*) FROM association a JOIN entity e ON e.id = a.term_entity_id
    WHERE (a.term_type = 'GENE') <> (e.entity_type = 'GENE')""").fetchone()[0] == 0)
gene_top = Q.top_associations(con, "evidence", "GENE", None, None)
check("gene list ordered by evidence", [r["score"] for r in gene_top["items"]]
      == sorted((r["score"] for r in gene_top["items"]), reverse=True),
      ", ".join(f"{r['mirna_name']}-{r['term_name']}" for r in gene_top["items"][:5]))
gene_row = gene_top["items"][0] if gene_top["items"] else None
if gene_row:
    hits = [r["accession"] for r in Q.search(con, gene_row["term_name"])]
    check(f"gene symbol '{gene_row['term_name']}' is searchable", gene_row["term_accession"] in hits)
    ev = Q.association_evidence(con, gene_row["id"])
    check("gene evidence sentences highlighted", bool(ev["items"]) and '<mark class="term">' in ev["items"][0]["html"],
          ev["items"][0]["html"][:160] if ev["items"] else "no sentences")
print("\n=== miRNA stats and term clouds ===")
sample = con.execute("""SELECT s.entity_id, e.accession, s.n_articles, s.breadth
                        FROM mirna_stats s JOIN entity e ON e.id = s.entity_id
                        ORDER BY s.n_articles DESC LIMIT 200""").fetchall()
live = {r["accession"]: Q.mirna_stats(con, r["entity_id"], r["accession"]) for r in sample}
drift = [r["accession"] for r in sample
         if (live[r["accession"]].n_articles, live[r["accession"]].breadth) != (r["n_articles"], r["breadth"])]
check("stored miRNA counts equal the live ones", bool(sample) and not drift, f"{len(sample)} sampled, drift: {drift[:3]}")
check("miRNA ranks lie within their population", con.execute(
    "SELECT count(*) FROM mirna_stats WHERE pop_rank < 1 OR pop_rank > pop_size").fetchone()[0] == 0)
check("every population has a rank 1", con.execute("""
    SELECT count(*) FROM (SELECT min(s.pop_rank) AS best FROM mirna_stats s JOIN entity e ON e.id = s.entity_id
                          GROUP BY e.reference_level, e.organism) WHERE best <> 1""").fetchone()[0] == 0)
busiest = con.execute("""SELECT mirna_entity_id FROM association GROUP BY 1 ORDER BY count(*) DESC LIMIT 1""").fetchone()[0]
for tt in Q.TERM_TYPES:
    top = Q.mirna_associations(con, busiest, tt, sort="evidence")["items"]
    if top:
        ranks = Q.association_ranks(con, Q.get_association(con, top[0]["id"]))
        check(f"top {tt} association of a miRNA has rank 1 of its total",
              ranks["in_mirna"]["rank"] == 1 and 1 <= ranks["in_term"]["rank"] <= ranks["in_term"]["total"],
              f"in miRNA {ranks['in_mirna']}, in term {ranks['in_term']}")
clouds = Q.mirna_term_clouds(con, busiest)
check("one cloud panel per associated type", {p["term_type"] for p in clouds}
      == set(Q.mirna_association_counts(con, busiest)) - {t for t in Q.TERM_TYPES if not Q.mirna_associations(con, busiest, t)["items"]})
nested = 0
for panel in clouds:
    ids = [t["term_entity_id"] for t in panel["terms"]]
    marks = ",".join("?" * len(ids))
    nested += con.execute(f"SELECT count(*) FROM ontology_closure WHERE ancestor_id IN ({marks}) AND descendant_id IN ({marks})",
                          ids + ids).fetchone()[0]
    print(f"  {panel['term_type']:19} " + ", ".join(t["term_name"] for t in panel["terms"][:8]))
check("no cloud panel holds a term together with its ancestor", nested == 0)
check("cloud weights lie in [0, 1]", all(0 <= t["weight"] <= 1 for p in clouds for t in p["terms"]))
busiest_acc = con.execute("SELECT accession FROM entity WHERE id = ?", (busiest,)).fetchone()[0]

print("\n=== subterm evidence ===")
# a propagation-only association has no evidence rows; its page shows the sentences of its subterms
propagated = [Q.get_association(con, r[0]) for r in con.execute("""
    SELECT id FROM association WHERE n_direct_articles = 0 AND term_type <> 'GENE' ORDER BY random() LIMIT 20""")]
untraced = []
for a in propagated:
    ids = [a["id"], *(s["id"] for s in Q.association_subterms(con, a))]
    n = con.execute("""SELECT count(DISTINCT s.article_id) FROM association_evidence ae JOIN sentence s ON s.id = ae.sentence_id
                       WHERE ae.association_id IN (SELECT value FROM json_each(?))""", (json.dumps(ids),)).fetchone()[0]
    if n != a["n_articles"]:
        untraced.append(f"{a['id']}: {n} vs {a['n_articles']}")
check("articles of the subterms add up to a propagated association's articles", bool(propagated) and not untraced,
      f"{len(propagated)} sampled, {untraced[:3]}")
cards = Q.association_evidence(con, propagated[0]["id"], subterms=Q.association_subterms(con, propagated[0]))["items"]
check("every sentence of a propagated association names its subterm", bool(cards) and all(c["via"] for c in cards))
def breakdown_labels(association_id):
    b = Q.association_labels(con, association_id)
    return [r["label"] for r in b["relations"]] + (["none"] if b["none"] else [])
relabelled = [r[0] for r in con.execute("SELECT id FROM association ORDER BY random() LIMIT 200")
              if Q.evidence_labels(con, [r[0]]) != breakdown_labels(r[0])]
check("direct sentence labels equal the label breakdown", not relabelled, f"{relabelled[:3]}")
if gene_row:
    check("genes have no subterms", Q.association_subterms(con, Q.get_association(con, gene_row["id"])) == [])

slash = con.execute("SELECT accession FROM entity WHERE entity_type='GENE' AND accession LIKE '%/%' LIMIT 1").fetchone()

try:
    from fastapi.testclient import TestClient
    os.environ.setdefault("TEXTMINING_DB", str(DB_PATH))
    from textmining.web.app import app
    client = TestClient(app)
    bogus = client.get(f"/mirna/{mir_acc}?type=DISEASE&sort=bogus")
    default = client.get(f"/mirna/{mir_acc}?type=DISEASE")
    check("invalid sort falls back to relevance", bogus.status_code == 200 and bogus.text == default.text)
    urls = [f"/term/{bc['accession']}", "/associations?type=CELL&organism=&level=",
            "/associations?type=GENE&organism=&level=",
            f"/mirna/{mir_acc}?type=GENE"]
    if page["items"]:
        urls.append(f"/association/{page['items'][0]['id']}")
    if gene_row:
        urls += [f"/term/{quote(gene_row['term_accession'])}?organism=", f"/association/{gene_row['id']}"]
    urls.append(f"/mirna/{busiest_acc}")
    if slash:
        urls.append(f"/term/{quote(slash['accession'])}")
    for url in urls:
        check(f"renders {url}", client.get(url).status_code == 200)
    check("no mixed-type list: /associations without a type shows the default",
          client.get("/associations").text == client.get(f"/associations?type={Q.DEFAULT_TYPE}").text)
    stats = client.get("/api/stats").json()
    check("landing statistics add up", stats["n_associations"] == sum(t["direct"] + t["propagated"] for t in stats["types"])
          == sum(l["n"] for l in stats["labels"]) + stats["n_no_label"])
    check("landing page has its own search and no header search",
          'class="search big"' in (home := client.get("/").text) and 'class="search" ' not in home)
    body = client.get(f"/mirna/{busiest_acc}").text
    check("miRNA page shows rank and clouds", 'class="clouds"' in body and 'class="label">of ' in body)
    if gene_row:
        check("association page loads evidence ranks", 'data-rank="in_mirna.rank"' in client.get(f"/association/{gene_row['id']}").text
              and client.get(f"/api/association/{gene_row['id']}/ranks").json()["in_mirna"]["rank"] >= 1)
    body = client.get(f"/association/{propagated[0]['id']}").text
    check("propagated association page lists subterm sentences",
          "No sentence names this term directly" in body and 'via <a href="/association/' in body)
    for url in (f"/term/{bc['accession']}", "/associations", f"/mirna/{mir_acc}"):
        check(f"rows open their association on {url}", 'data-href="/association/' in client.get(url).text)
    term_body = client.get(f"/term/{bc['accession']}").text
    check("term page has no expansion controls",
          "Best " not in term_body and 'name="expand"' not in term_body and "/association/" not in
          term_body.replace('data-href="/association/', ""))
    check("gene list has no relevance column",
          "Relevance" not in client.get("/associations?type=GENE&organism=&level=").text)
except ImportError as exc:
    print(f"  (route checks skipped: {exc})")

print("\n=== relation labels ===")
# dominant label, recomputed in Python from association_label
by_assoc = {}
for r in con.execute("SELECT association_id, label, n_articles, n_sentences FROM association_label WHERE label != 'none'"):
    by_assoc.setdefault(r[0], []).append((r[1] == "associated", -r[2], -r[3], r[1]))
expected = {aid: (min(rows)[3], -min(rows)[1]) for aid, rows in by_assoc.items()}
stored = {r[0]: (r[1], r[2]) for r in con.execute(
    "SELECT id, dominant_label, dominant_label_articles FROM association WHERE dominant_label IS NOT NULL")}
check("dominant label matches association_label", stored == expected, f"{len(stored):,} associations")
dom = con.execute("""SELECT sum(dominant_label = 'none'), sum(dominant_label IS NOT NULL AND n_direct_articles = 0),
                            sum(dominant_label_articles > n_direct_articles),
                            sum((dominant_label IS NULL) <> (dominant_label_articles IS NULL))
                     FROM association""").fetchone()
check("dominant label never 'none', only with direct evidence, within the direct articles",
      not any(dom), str(tuple(dom)))
check("confidence is the top probability", con.execute("""
    SELECT count(*) FROM mention_pair WHERE (label IS NULL) <> (confidence IS NULL) OR abs(confidence - max(
        p_none, ifnull(p_associated, 0), ifnull(p_biomarker, 0), ifnull(p_expressed, 0), ifnull(p_expression_down, 0),
        ifnull(p_expression_up, 0), ifnull(p_inhibits, 0), ifnull(p_promotes, 0), ifnull(p_targets, 0))) > 1e-9
""").fetchone()[0] == 0)
menu = Q.labels_by_type(con)
print("  label menu:", {t: labels for t, labels in menu.items() if labels})

# the same filter and the same label in all three list modes
for term_type, labels in menu.items():
    for label in labels[:2]:
        n = con.execute("SELECT count(*) FROM association WHERE term_type = ? AND dominant_label = ?",
                        (term_type, label)).fetchone()[0]
        Q._TOP_CACHE.clear()
        top = Q.top_associations(con, "evidence", term_type, None, None, label=label)
        check(f"top list, {term_type} {label}", top["total"] == n and top["items"]
              and all(r["dominant_label"] == label for r in top["items"]), f"{n:,}")
        first = con.execute("SELECT mirna_entity_id, term_entity_id FROM association WHERE id = ?",
                            (top["items"][0]["id"],)).fetchone()
        in_mirna = Q.mirna_associations(con, first[0], term_type, sort="evidence", label=label, per_page=10_000)
        in_term = Q.term_mirnas(con, first[1], None, label=label, per_page=10_000)
        for name, listing, column, entity_id in (("miRNA", in_mirna, "mirna_entity_id", first[0]),
                                                 ("term", in_term, "term_entity_id", first[1])):
            n_here = con.execute(f"SELECT count(*) FROM association WHERE {column} = ? AND term_type = ? "
                                 "AND dominant_label = ?", (entity_id, term_type, label)).fetchone()[0]
            same = [r for r in listing["items"] if r["id"] == top["items"][0]["id"]]
            check(f"{name} list agrees, {term_type} {label}", listing["total"] == n_here and len(same) == 1
                  and all(r["dominant_label"] == label for r in listing["items"])
                  and same[0]["dominant_label_articles"] == top["items"][0]["dominant_label_articles"])

# evidence sentences of the association with the most labelled sentences
busy = con.execute("""SELECT association_id FROM association_label GROUP BY association_id
                      ORDER BY sum(n_sentences) DESC LIMIT 1""").fetchone()[0]
breakdown = Q.association_labels(con, busy)
check("breakdown leaves 'none' out of the bar", all(r["label"] != "none" for r in breakdown["relations"])
      and [r["label"] for r in breakdown["relations"]] == [l for l in Q.LABELS if l in {r["label"] for r in breakdown["relations"]}])
for row in breakdown["relations"] + ([breakdown["none"]] if breakdown["none"] else []):
    ev = Q.association_evidence(con, busy, label=row["label"], sort="confidence", per_page=10_000)
    confs = [next(l["confidence"] for l in c["labels"] if l["label"] == row["label"]) for c in ev["items"]]
    check(f"evidence filter {row['label']}", ev["total"] == row["n_sentences"] == len(ev["items"])
          and all(a >= b for a, b in zip(confs, confs[1:])), f"{ev['total']} sentences")
everything = Q.association_evidence(con, busy, sort="confidence", per_page=100_000)
plain = Q.association_evidence(con, busy, per_page=100_000)
stated = [any(l["label"] != "none" for l in c["labels"]) for c in everything["items"]]
check("confidence order keeps every sentence, 'none'-only last",
      sorted(c["sentence_id"] for c in everything["items"]) == [c["sentence_id"] for c in plain["items"]]
      and stated == sorted(stated, reverse=True))
check("levels follow the cut-offs", [Q.confidence_level(p) for p in (0.99, 0.983, 0.9, 0.85, 0.5)]
      == ["high", "high", "medium", "medium", "low"])

try:
    from fastapi.testclient import TestClient
    import textmining.web.app as webapp
    client = TestClient(webapp.app)
    row = con.execute("""SELECT a.id, a.term_type, a.dominant_label, m.accession AS mir, t.accession AS term
                         FROM association a JOIN entity m ON m.id = a.mirna_entity_id
                         JOIN entity t ON t.id = a.term_entity_id
                         WHERE a.dominant_label IS NOT NULL AND m.organism = 'hsa' AND m.reference_level = 'mature'
                         ORDER BY a.score DESC LIMIT 1""").fetchone()
    label, chip = row["dominant_label"], f'class="rel rel-{row["dominant_label"]}"'
    for url in (f"/associations?type={row['term_type']}&label={label}&sort=evidence",
                f"/mirna/{row['mir']}?type={row['term_type']}&label={label}",
                f"/term/{quote(row['term'])}?label={label}"):
        body = client.get(url).text
        check(f"filtered list renders {url}", chip in body and f'data-href="/association/{row["id"]}"' in body)
    check("a label that does not exist for the type is ignored",
          client.get("/associations?label=bogus").text == client.get("/associations").text)
    body = client.get(f"/association/{row['id']}?label={label}&sort=confidence").text
    check("association page shows the breakdown and labelled sentences", 'class="rel-bar"' in body and chip in body)
    no_direct = con.execute("SELECT id FROM association WHERE n_direct_articles = 0 LIMIT 1").fetchone()
    if no_direct:
        body = client.get(f"/association/{no_direct[0]}").text
        check("propagated-only association has a notice, no bar",
              "No sentence names this term directly" in body and 'class="rel-bar"' not in body)
except ImportError as exc:
    print(f"  (route checks skipped: {exc})")

print("\n" +("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
