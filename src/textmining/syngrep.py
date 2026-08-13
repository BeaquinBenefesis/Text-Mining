import subprocess
import logging
from dataclasses import dataclass
import os
from textmining.types import HitType

logger = logging.getLogger(__name__)

SYNGREP_PATH = '/home/proj/software/own/syngrep/syngrepJavaOnGrid.sh'

@dataclass
class SynGrepResult:
    hits_path: str
    context_path: str
    tmp_path: str
    synfile_map_path: str
    synfile_type_map_path: str

def _write_synfile_type_map(synonyms: dict[HitType, list[str]], abbrevs: dict[HitType, list[str]], path: str):
    logger.debug(
        "Writing synfile type map to %s: %d synonym type(s), %d abbrev type(s)",
        path, len(synonyms), len(abbrevs),
    )
    with open(path, 'w') as fh:
        for hit_type, paths in synonyms.items():
            for p in paths:
                fh.write(f'{p}\t{hit_type.name}\t{False}\n')
        for hit_type, paths in abbrevs.items():
            for p in paths:
                fh.write(f'{p}\t{hit_type.name}\t{True}\n')

def run_syngrep(sentence_pattern: str,
                synonyms: dict[HitType, list[str]],
                output_dir: str,
                abbrev_synonyms: dict[HitType, list[str]] = {},
                within_word: list[str] | None = None,
                output_name: str = 'output',
                word_char: str = 'SYNONYMS',
                ntasks: int = 1,
                abbrev: bool = True,
                syngrep_script: str = SYNGREP_PATH) -> SynGrepResult:
    os.makedirs(output_dir, exist_ok=True)
    logger.info(
        "Starting syngrep task: output_name=%s, output_dir=%s, ntasks=%d, abbrev=%s",
        output_name, output_dir, ntasks, abbrev,
    )
    synfile_map_path = None
    synfile_type_map_path = None
    raw_synonyms = [p for paths in synonyms.values() for p in paths]
    raw_abbrevs = [p for paths in abbrev_synonyms.values() for p in paths] if abbrev_synonyms else []
    combined = []
    combined.extend(raw_synonyms)
    combined.extend(raw_abbrevs)
    logger.debug(
        "Synonym files: %d standard, %d abbrev, entity types=%s",
        len(raw_synonyms), len(raw_abbrevs), [t.name for t in synonyms.keys()],
    )
    program_args = ['-wordChar', word_char, '-syn', *combined]

    if abbrev:
        program_args.extend(['-abbrev', 'relaxed'])

    if within_word:
        program_args.extend(['-withinWord', *[os.path.basename(p) for p in within_word]])

    out = os.path.join(output_dir, output_name)
    cmd = ['bash', syngrep_script,
           '--ntasks', str(ntasks),
           '--sentences', sentence_pattern,
           '--out', out,
           '--wd', output_dir,
           '--', *program_args]
    parameter_string = ' '.join(str(arg) for arg in cmd)
    logger.info("Running syngrep with parameters:\n%s", parameter_string)
    try:
        synfile_type_map_path = os.path.join(output_dir, 'synfile_type.map')
        _write_synfile_type_map(synonyms, abbrev_synonyms, synfile_type_map_path)
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.debug("syngrep stdout:\n%s", result.stdout)
        if result.stderr:
            logger.debug("syngrep stderr:\n%s", result.stderr)
        synfile_map_path = os.path.join(output_dir, 'synfile.map')
        logger.info("syngrep completed successfully: hits=%s.hits", out)
    except subprocess.CalledProcessError as e:
        logger.error(
            "syngrep failed (exit %d)\nstdout:\n%s\nstderr:\n%s",
            e.returncode, e.stdout, e.stderr,
        )
        raise RuntimeError(
            f'syngrep failed (exit {e.returncode}):\n'
            f'stdout:\n{e.stdout}\nstderr:\n{e.stderr}'
        ) from e

    return SynGrepResult(
        hits_path=f'{out}.hits',
        context_path=f'{out}.context',
        tmp_path=os.path.join(output_dir, 'tmp'),
        synfile_map_path=synfile_map_path,
        synfile_type_map_path=synfile_type_map_path,
    )