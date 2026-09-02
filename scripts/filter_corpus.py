import argparse
import glob
import logging
import os
import shlex
import shutil
import subprocess
from pathlib import Path
import re
from pipelines.pipeline import run_existing_pipeline
from textmining.enums import HitType
from textmining.syngrep import run_syngrep, SynGrepResult
from textmining.resources import MIR_SYNS
from textmining.paths import SCRIPTS_DIR
from textmining.config import MirnaExistingSyngrepPipelineConfig
from textmining.normalization_resources import MirResourceLoader
from textmining.hit_utils import HitProcessor
from textmining.normalization import MirIdMapper


logger = logging.getLogger(__name__)

PREPARE_CORPUS_SH = SCRIPTS_DIR / "corpus" / "prepare_corpus.sh"
_ARTICLE_ID_AWK = 'n=split($1,a,"."); id=a[1]; for (i=2;i<=n-2;i++) id=id"."a[i];'
SUFFIX_REGEX = re.compile(MirResourceLoader._build_mirna_suffix_pattern())

# A sentence id is <article_id>.<section_num>.<sentence_num>, where article_id may
# itself contain dots (PMC ids do not, but the corpus is not guaranteed to be PMC-only).
# Anything with whitespace in field 1 is a torn line, not an id.
SENTENCE_ID_REGEX = r'^[A-Za-z0-9][A-Za-z0-9._-]*\.[0-9]+\.[0-9]+$'

# Single pass over the final chunk files, checking:
#   1. every line's field 1 is a well-formed sentence id
#   2. every line has at least an id field and a text field
#   3. the number of distinct articles matches the extracted article id list
#   4. no article's sentences are spread over more than one chunk
# Chunks are article-aligned and internally sorted, so tracking the previous article
# per file is enough to spot an article re-entered from a different chunk.
VERIFY_AWK = r'''
function article_id(sid,   n, parts, out, i) {
    n = split(sid, parts, ".")
    out = parts[1]
    for (i = 2; i <= n - 2; i++) out = out "." parts[i]
    return out
}
function example(tag, line) {
    if (++shown[tag] <= max_examples)
        printf "%s\t%s:%d\t%s\n", tag, FILENAME, FNR, substr(line, 1, 160) > "/dev/stderr"
}
BEGIN { id_regex = ENVIRON["SENTENCE_ID_REGEX"] }
FNR == 1 { prev = "" }
{
    total++
    if ($1 !~ id_regex) { bad_id++; example("BAD_ID", $0); next }
    if (NF < 2)         { bad_fields++; example("BAD_FIELDS", $0); next }
    a = article_id($1)
    if (a == prev) next
    if (a in seen) {
        if (seen[a] != FILENAME) { split_article++; example("SPLIT_ARTICLE", $0) }
    } else {
        articles++
    }
    seen[a] = FILENAME
    prev = a
}
END {
    printf "total=%d\nbad_id=%d\nbad_fields=%d\nsplit_article=%d\narticles=%d\n",
           total, bad_id + 0, bad_fields + 0, split_article + 0, articles + 0
}
'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a miRNA-only syngrep pass over a corpus, then filter the "
                     "corpus down to full articles that had at least one hit and "
                     "hand that subset to prepare_corpus.sh."
    )
    parser.add_argument(
        "--sentence-pattern", required=True, nargs="+",
        help='One or more quoted glob patterns for the per-file sentence corpus, e.g. '
             '"/path/to/PUBMED/*.sent" "/path/to/PMC/pmc/*.sent"',
    )
    parser.add_argument(
        "--output-dir", required=True, type=Path,
        help="Directory for syngrep output, the article id list, and the filtered/prepared corpus",
    )
    parser.add_argument("--output-name", default="mir_filter", help="Basename for the syngrep output files")
    parser.add_argument(
        "--existing-hits", type=Path, default=None,
        help="Skip running syngrep and filter using this existing .hits file instead "
             "(--ntasks is ignored in this case)",
    )
    parser.add_argument("--ntasks", type=int, default=50, help="syngrep grid tasks")
    parser.add_argument(
        "--jobs", type=int, default=8,
        help="Parallel awk workers for filtering sentence files (see filter_sentences)",
    )
    parser.add_argument(
        "--skip-verify", action="store_true",
        help="Skip the final integrity pass over the prepared chunks (that pass reads the "
             "whole prepared corpus once, which takes a while on a 450GB+ input)",
    )

    # passthrough to prepare_corpus.sh
    parser.add_argument("--chunks", type=int, default=1, help="prepare_corpus.sh -n: number of article-aligned chunks")
    parser.add_argument(
        "--keep-sorted", action="store_true",
        help="prepare_corpus.sh -k: keep the intermediate fully-sorted file when splitting into chunks",
    )
    return parser.parse_args()

def build_mir_only_synfile_maps() -> tuple[dict[str, Path], dict[str, tuple[HitType, bool]]]:
    """Hand-built equivalent of the synfile.map/synfile_type.map that run_syngrep would
    produce for this script's own syngrep call (synonyms={HitType.MIR: [MIR_SYNS]}, no
    abbrev_synonyms). Valid only because that call always passes a single synonym file,
    which the external syngrep tool always assigns file_id "0" (confirmed against
    outputs/small_test/synfile.map, a prior single-synfile run) -- do not reuse this for
    a .hits file produced by a multi-entity-type/multi-synfile run."""
    return {"0": Path(MIR_SYNS)}, {Path(MIR_SYNS).name: (HitType.MIR, False)}


def extract_article_ids(
    hits_path: Path,
    synfile_map: dict[str, Path],
    synfile_type_map: dict[str, tuple[HitType, bool]],
    article_ids_path: Path,
) -> int:
    hit_stream = HitProcessor._iter_syngrep_hits(hits_path=hits_path,
                                    synfile_map=synfile_map,
                                    synfile_type_map=synfile_type_map)

    article_ids = {
        hit.article_id for hit in hit_stream
        if hit.entity_type == HitType.MIR
        and (SUFFIX_REGEX.search(hit.suffix) or MirIdMapper.resolve_token(hit.entity_id) == 'bantam')
    }
    
    with open(article_ids_path, 'w') as out:
        for article_id in sorted(article_ids):
            out.write(f'{article_id}\n')

    return len(article_ids)

def filter_sentences(
    sentence_files: list[str], article_ids_path: Path, filtered_path: Path, filelist_path: Path,
    parts_dir: Path, jobs: int = 8
) -> None:
    """Stream every matched sentence file through awk, keeping only lines whose
    article id is in the id set. Files are handed to awk via xargs -P (batched
    to stay under ARG_MAX, run `jobs` at a time) instead of loaded in Python or
    processed one file-batch at a time, so this scales to however many files a
    450GB+ corpus is split into and to however many cores are free.

    Each worker writes to its OWN part file, which are concatenated afterwards.
    They must not share a single redirect: awk flushes in ~4KB blocks, writes
    that large to a shared file description are not atomic, and block boundaries
    almost never fall on a line boundary -- so concurrent workers splice halves
    of each other's lines together (observed: ~0.15% of output lines torn, half
    of them left as id-less sentence fragments). Order across parts does not
    matter, prepare_corpus.sh sorts the result anyway."""
    filelist_path.write_text("\n".join(sentence_files) + "\n")
    awk_script = (
        'BEGIN{while ((getline id < idfile) > 0) ids[id]=1; close(idfile)} '
        '{' + _ARTICLE_ID_AWK + ' if (id in ids) print}'
    )
    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    parts_dir.mkdir(parents=True)

    batch_size = max(1, -(-len(sentence_files) // jobs))  # ceil(n_files / jobs) files per worker
    # $$ is expanded by each `sh -c` worker (its own pid), not by the outer shell.
    worker = (
        f'awk -F"\\t" -v idfile={shlex.quote(str(article_ids_path))} {shlex.quote(awk_script)} "$@" '
        f'> {shlex.quote(str(parts_dir))}/part.$$'
    )
    cmd = (
        f'LC_ALL=C xargs -a {shlex.quote(str(filelist_path))} -d "\\n" -n {batch_size} -P {jobs} '
        f'sh -c {shlex.quote(worker)} _'
    )
    subprocess.run(cmd, shell=True, check=True)

    parts = sorted(parts_dir.glob("part.*"))
    if not parts:
        raise RuntimeError(f"No part files produced in {parts_dir}; filtering step wrote nothing")
    with open(filtered_path, "wb") as out:
        subprocess.run(["cat", *[str(p) for p in parts]], stdout=out, check=True)


def verify_output(chunk_files: list[Path], article_ids_path: Path, max_examples: int = 5) -> None:
    """Read the prepared corpus once and assert it is intact: well-formed sentence ids,
    no truncated lines, the expected number of articles, and no article split across
    chunks. Raises RuntimeError on any violation; a few offending lines per failure
    class are logged so the cause is diagnosable without a second pass."""
    expected_articles = sum(1 for _ in article_ids_path.open())
    logger.info("Verifying %d output file(s) against %d expected articles",
                len(chunk_files), expected_articles)

    proc = subprocess.run(
        ["awk", "-F", "\t",
         "-v", f"max_examples={max_examples}",
         VERIFY_AWK, *[str(f) for f in chunk_files]],
        capture_output=True, text=True, env={**os.environ, "LC_ALL": "C", "SENTENCE_ID_REGEX": SENTENCE_ID_REGEX},
        check=True,
    )
    stats = dict(
        (k, int(v)) for k, v in
        (line.split("=", 1) for line in proc.stdout.split() if "=" in line)
    )
    for line in proc.stderr.splitlines():
        logger.warning("verify: %s", line)

    problems = []
    if stats.get("bad_id"):
        problems.append(f"{stats['bad_id']} line(s) with a malformed sentence id (torn lines)")
    if stats.get("bad_fields"):
        problems.append(f"{stats['bad_fields']} line(s) with fewer than 2 tab-separated fields")
    if stats.get("split_article"):
        problems.append(f"{stats['split_article']} article(s) spread over more than one chunk")
    if stats.get("articles") != expected_articles:
        problems.append(
            f"{stats.get('articles')} distinct articles in the output, expected {expected_articles}"
        )

    if problems:
        raise RuntimeError("Output verification failed: " + "; ".join(problems))
    logger.info("Verification passed: %d sentences, %d articles, no torn or misplaced lines",
                stats.get("total", 0), stats.get("articles", 0))


def cleanup(extra_paths: list[Path], parts_dir: Path | None = None,
            syngrep_result: SynGrepResult | None = None) -> None:
    """Remove intermediate files this script produced (and syngrep's, if it ran),
    leaving only prepare_corpus.sh's final (filtered) sentence file(s) in output_dir.
    When filtering from an --existing-hits file there's no syngrep_result, and that
    file is never touched -- it wasn't produced by this run."""
    paths = list(extra_paths)
    if syngrep_result is not None:
        paths += [
            syngrep_result.hits_path,
            syngrep_result.context_path,
            syngrep_result.synfile_map_path,
            syngrep_result.synfile_type_map_path,
        ]
    for p in paths:
        if p is None:
            continue
        path = Path(p)
        if path.exists():
            path.unlink()
    if parts_dir is not None and parts_dir.exists():
        shutil.rmtree(parts_dir)
    if syngrep_result is not None and syngrep_result.tmp_path and Path(syngrep_result.tmp_path).exists():
        shutil.rmtree(syngrep_result.tmp_path)


def main():
    logging.basicConfig(level=logging.INFO)
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    sentence_pattern_arg = " ".join(args.sentence_pattern)

    syngrep_result = None
    if args.existing_hits:
        if not args.existing_hits.exists():
            raise FileNotFoundError(f"--existing-hits file not found: {args.existing_hits}")
        hits_path = args.existing_hits
        logger.info("Using existing hits file %s, skipping syngrep", hits_path)
    else:
        syngrep_result = run_syngrep(
            sentence_pattern=sentence_pattern_arg,
            synonyms={HitType.MIR: [MIR_SYNS]},
            output_dir=str(args.output_dir),
            output_name=args.output_name,
            no_abbrev_syn_list=[MIR_SYNS],
            within_word=[MIR_SYNS],
            abbrev_mode="relaxed",
            ntasks=args.ntasks,
        )
        hits_path = Path(syngrep_result.hits_path)

    article_ids_path = args.output_dir / f"{args.output_name}_article_ids.txt"
    logger.info("Extracting article ids from %s", hits_path)
    if syngrep_result is not None:
        synfile_map = HitProcessor.parse_synfile_map(syngrep_result.synfile_map_path)
        synfile_type_map = HitProcessor.parse_synfile_type_map(syngrep_result.synfile_type_map_path)
    else:
        synfile_map, synfile_type_map = build_mir_only_synfile_maps()
    n_articles = extract_article_ids(hits_path, synfile_map, synfile_type_map, article_ids_path)
    logger.info("%d articles contain at least one miRNA hit", n_articles)

    sentence_files = sorted({f for pattern in args.sentence_pattern for f in glob.glob(pattern)})
    if not sentence_files:
        raise ValueError(f"No sentence files matched pattern(s): {args.sentence_pattern}")

    filelist_path = args.output_dir / f"{args.output_name}_filelist.txt"
    filtered_path = args.output_dir / f"{args.output_name}_filtered.sent"
    parts_dir = args.output_dir / f"{args.output_name}_parts"
    logger.info("Filtering %d sentence file(s) down to the matched articles", len(sentence_files))
    filter_sentences(sentence_files, article_ids_path, filtered_path, filelist_path, parts_dir,
                     jobs=args.jobs)

    prepare_cmd = [
        "bash", str(PREPARE_CORPUS_SH),
        "-f", str(filtered_path),
        "-o", str(args.output_dir),
        "-n", str(args.chunks),
    ]
    if args.keep_sorted:
        prepare_cmd.append("-k")
    logger.info("Running prepare_corpus.sh")
    subprocess.run(prepare_cmd, check=True)

    if args.skip_verify:
        logger.info("Skipping output verification (--skip-verify)")
    else:
        if args.chunks == 1:
            chunk_files = [args.output_dir / "sorted_output.sent"]
        else:
            chunk_files = sorted(
                args.output_dir.glob("chunk_*.sent"),
                key=lambda p: int(p.stem.split("_")[1]),
            )
        verify_output(chunk_files, article_ids_path)

    logger.info("Cleaning up intermediate files")
    cleanup([filtered_path, article_ids_path, filelist_path], parts_dir, syngrep_result)


if __name__ == "__main__":
    main()
