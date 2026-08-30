import argparse
import glob
import logging
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

    # passthrough to prepare_corpus.sh
    parser.add_argument("--chunks", type=int, default=1, help="prepare_corpus.sh -n: number of article-aligned chunks")
    parser.add_argument(
        "--keep-sorted", action="store_true",
        help="prepare_corpus.sh -k: keep the intermediate fully-sorted file when splitting into chunks",
    )
    return parser.parse_args()


def extract_article_ids_old(hits_path: Path, article_ids_path: Path, sort_mem: str = "40G", sort_jobs: int = 16) -> int:
    """Stream the .hits file through awk to pull the article id prefix of every
    sentence_id, then dedupe with an external sort so nothing needs to fit in
    Python memory. Returns the number of distinct article ids found.

    hits_path's first column is hit_id = file_name:sentence_id (unlike the
    corpus, whose first column is bare sentence_id), so the file_name: prefix
    is stripped before applying the shared article-id extraction."""
    awk_expr = '{sub(/^[^:]*:/, "", $1); ' + _ARTICLE_ID_AWK + ' print id}'
    cmd = (
        f'LC_ALL=C awk -F"\\t" {shlex.quote(awk_expr)} {shlex.quote(str(hits_path))} '
        f'| LC_ALL=C sort -u -S {sort_mem} --parallel={sort_jobs} '
        f'> {shlex.quote(str(article_ids_path))}'
    )
    subprocess.run(cmd, shell=True, check=True)
    result = subprocess.run(["wc", "-l", str(article_ids_path)], capture_output=True, text=True, check=True)
    return int(result.stdout.split()[0])

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
    sentence_files: list[str], article_ids_path: Path, filtered_path: Path, filelist_path: Path, jobs: int = 8
) -> None:
    """Stream every matched sentence file through awk, keeping only lines whose
    article id is in the id set. Files are handed to awk via xargs -P (batched
    to stay under ARG_MAX, run `jobs` at a time) instead of loaded in Python or
    processed one file-batch at a time, so this scales to however many files a
    450GB+ corpus is split into and to however many cores are free."""
    filelist_path.write_text("\n".join(sentence_files) + "\n")
    awk_script = (
        'BEGIN{while ((getline id < idfile) > 0) ids[id]=1; close(idfile)} '
        '{' + _ARTICLE_ID_AWK + ' if (id in ids) print}'
    )
    batch_size = max(1, -(-len(sentence_files) // jobs))  # ceil(n_files / jobs) files per worker
    cmd = (
        f'LC_ALL=C xargs -a {shlex.quote(str(filelist_path))} -d "\\n" -n {batch_size} -P {jobs} '
        f'awk -F"\\t" -v idfile={shlex.quote(str(article_ids_path))} {shlex.quote(awk_script)} '
        f'> {shlex.quote(str(filtered_path))}'
    )
    subprocess.run(cmd, shell=True, check=True)


def cleanup(extra_paths: list[Path], syngrep_result: SynGrepResult | None = None) -> None:
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
    logger.info("Filtering %d sentence file(s) down to the matched articles", len(sentence_files))
    filter_sentences(sentence_files, article_ids_path, filtered_path, filelist_path, jobs=args.jobs)

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

    logger.info("Cleaning up intermediate files")
    cleanup([filtered_path, article_ids_path, filelist_path], syngrep_result)


if __name__ == "__main__":
    main()
