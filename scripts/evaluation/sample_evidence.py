"""Sample evidence sentences for labelling.

    python scripts/evaluation/sample_evidence.py N out_prefix [--db db/atlas.db] [--seed 0]
                                                 [--mode association|sentence|sentence-balanced]

Writes <out_prefix>_llm.tsv and <out_prefix>_human.tsv with the same rows in the
same order, joined by sentence_id.

The two co-occurring mentions are marked: in the LLM file they are replaced by
$MIR and $<TERM_TYPE> so the model judges the sentence, not the names; in the
human file they stay visible, wrapped as <mir>...</mir> and <term_type>...</term_type>.

--mode association (default): one sentence per random association. N is split
evenly over the term types (remainder to the first ones). Each association is
used at most once and every sentence comes from a different article. Only
associations with direct evidence qualify: propagated-only associations
(n_direct_articles = 0) have no association_evidence rows.

--mode sentence: N sentences drawn uniformly at random from all evidence
sentences, then one random miRNA-term pair from each. No quotas per term type
and no exclusions by article or association, so the sample follows the corpus:
frequent associations and term types appear in proportion to their evidence.

--mode sentence-balanced: as sentence, but N is split evenly over the term
types (remainder to the first ones). Random sentences are read until every
type has its share; from each sentence one random pair is taken among the types
that still need sentences. Still no exclusions by article or association.
"""
import argparse
import random
from collections import defaultdict
from pathlib import Path
from textmining.bert import masked, substitute, tagged, valid_spans
from textmining.db.connect import DB_PATH, open_readonly
from textmining.web.highlight import extend_mirna_span
from textmining.web.queries import TERM_TYPES


def pick_sentence(con, assoc_id: int, term_type: str, used_articles: set[int]) -> tuple[int, int, str, str] | None:
    rows = con.execute(
        """SELECT e.sentence_id, s.article_id, e.mirna_start, e.mirna_end, e.term_start, e.term_end, s.sentence_text
           FROM association_evidence e JOIN sentence s ON s.id = e.sentence_id
           WHERE e.association_id = ? ORDER BY e.id""",
        (assoc_id,),
    ).fetchall()
    random.shuffle(rows)
    for r in rows:
        if r["article_id"] in used_articles:
            continue
        text = r["sentence_text"]
        mir_start, mir_end = extend_mirna_span(text, r["mirna_start"], r["mirna_end"])
        spans = [(mir_start, mir_end, "MIR"), (r["term_start"], r["term_end"], term_type)]
        if valid_spans(text, spans):
            return (r["article_id"], r["sentence_id"],
                    substitute(text, spans, masked), substitute(text, spans, tagged))
    return None


def sample_associations(con, n: int) -> list[list]:
    ids_by_type = defaultdict(list)
    for assoc_id, term_type in con.execute(
            "SELECT id, term_type FROM association WHERE n_direct_articles > 0 ORDER BY id"):
        ids_by_type[term_type].append(assoc_id)

    base, extra = divmod(n, len(TERM_TYPES))
    used_articles: set[int] = set()
    out_rows = []
    for i, term_type in enumerate(TERM_TYPES):
        quota = base + (i < extra)
        candidates = ids_by_type[term_type]
        random.shuffle(candidates)  # association ids are unique, so no association repeats
        taken = 0
        for assoc_id in candidates:
            if taken == quota:
                break
            picked = pick_sentence(con, assoc_id, term_type, used_articles)
            if picked is None:
                continue
            article_id, *row = picked
            used_articles.add(article_id)
            out_rows.append(row)
            taken += 1
        print(f"{term_type}: {taken}/{quota} from {len(candidates)} associations")
    return out_rows


def sample_sentences(con, n: int, balanced: bool = False) -> list[list]:
    """n random evidence sentences, one random miRNA-term pair from each.

    With balanced, each term type gets an equal share of n, and a pair is only
    taken while its type still needs sentences.
    """
    base, extra = divmod(n, len(TERM_TYPES))
    quota = {t: base + (i < extra) for i, t in enumerate(TERM_TYPES)}
    by_type = defaultdict(int)
    sentence_ids = [r[0] for r in con.execute("SELECT id FROM sentence ORDER BY id")]
    random.shuffle(sentence_ids)
    con.execute("CREATE TEMP TABLE picked(id INTEGER PRIMARY KEY)")
    out_rows = []
    # association_evidence has no index on sentence_id, so each batch is one scan
    # of it. A batch of 2n leaves room for sentences without a taggable pair.
    for start in range(0, len(sentence_ids), 2 * n):
        batch = sentence_ids[start:start + 2 * n]
        con.execute("DELETE FROM picked")
        con.executemany("INSERT INTO picked VALUES (?)", [(i,) for i in batch])
        texts, pairs = {}, defaultdict(set)
        for r in con.execute(
                """SELECT e.sentence_id, e.mirna_start, e.mirna_end, e.term_start, e.term_end,
                          a.term_type, s.sentence_text
                   FROM association_evidence e JOIN picked p ON p.id = e.sentence_id
                   JOIN association a ON a.id = e.association_id
                   JOIN sentence s ON s.id = e.sentence_id"""):
            text = texts.setdefault(r["sentence_id"], r["sentence_text"])
            mir = extend_mirna_span(text, r["mirna_start"], r["mirna_end"])
            # one mention pair can back several associations: count it once
            pairs[r["sentence_id"]].add((*mir, r["term_start"], r["term_end"], r["term_type"]))
        for sentence_id in batch:
            if len(out_rows) == n:
                break
            usable = []
            for mir_start, mir_end, term_start, term_end, term_type in sorted(pairs[sentence_id]):
                spans = [(mir_start, mir_end, "MIR"), (term_start, term_end, term_type)]
                if balanced and by_type[term_type] >= quota[term_type]:
                    continue
                if valid_spans(texts[sentence_id], spans):  # overlapping spans cannot be tagged
                    usable.append(spans)
            if usable:
                spans = random.choice(usable)
                text = texts[sentence_id]
                by_type[spans[1][2]] += 1
                out_rows.append([sentence_id, substitute(text, spans, masked), substitute(text, spans, tagged)])
        if len(out_rows) == n:
            break
    print(f"{len(out_rows)}/{n} sentences; " + ", ".join(f"{t}: {c}" for t, c in sorted(by_type.items())))
    return out_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("n", type=int)
    parser.add_argument("out_prefix", type=Path)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--mode", choices=["association", "sentence", "sentence-balanced"], default="association")
    args = parser.parse_args()
    random.seed(args.seed)

    con = open_readonly(args.db, immutable=True)
    if args.mode == "association":
        out_rows = sample_associations(con, args.n)
    else:
        out_rows = sample_sentences(con, args.n, balanced=args.mode == "sentence-balanced")

    for suffix, column in (("llm", 1), ("human", 2)):
        path = args.out_prefix.with_name(f"{args.out_prefix.name}_{suffix}.tsv")
        with path.open("w") as fh:
            fh.write("sentence\tlabel\tsentence_id\n")
            fh.writelines(f'"{quote(row[column])}"\t\t{row[0]}\n' for row in out_rows)
        print(f"wrote {path}")


def quote(sentence: str) -> str:
    """Double embedded quotes so the quoted field parses as standard TSV."""
    return sentence.replace('"', '""')


if __name__ == "__main__":
    main()
