from .models import HitType
import subprocess
from dataclasses import dataclass
import os

SYNGREP_PATH = '/home/proj/software/own/syngrep/syngrepJavaOnGrid.sh'

@dataclass
class SynGrepResult:
    hits_path: str
    context_path: str
    tmp_path: str
    synfile_map_path: str
    synfile_type_map_path: str

def _write_synfile_type_map(synonyms: dict[HitType, list[str]], path: str):
    with open(path, 'w') as fh:
        for hit_type, paths in synonyms.items():
            for p in paths:
                fh.write(f'{p}\t{hit_type.name}\n')


def run_syngrep(sentence_pattern: str,
                synonyms: dict[HitType, list[str]],
                output_dir: str,
                within_word: list[str] | None = None,
                output_name: str = 'output',
                word_char: str = 'SYNONYMS',
                ntasks: int = 1,
                abbrev: bool = True,
                syngrep_script: str = SYNGREP_PATH) -> SynGrepResult:
    os.makedirs(output_dir, exist_ok=True)
    print('Starting syngrep task...')
    synfile_map_path = None
    synfile_type_map_path = None
    raw_synonyms = [p for paths in synonyms.values() for p in paths]
    program_args = ['-wordChar', word_char, '-syn', *raw_synonyms]
    
    if abbrev:
        program_args.extend(['-abbrev'])
    
    if within_word:
        program_args.extend(['-withinWord', *[os.path.basename(p) for p in within_word]])

    out = os.path.join(output_dir, output_name)
    cmd = ['bash', syngrep_script,
           '--ntasks', str(ntasks),
           '--sentences', sentence_pattern,
           '--out', out,
           '--wd', output_dir,
           '--', *program_args]
    parameter_string = ' '.join(cmd)
    print(f'Running with parameters:\n{parameter_string}')
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        synfile_map_path = os.path.join(output_dir, 'synfile.map')
        synfile_type_map_path = os.path.join(output_dir, 'synfile_type.map')
        _write_synfile_type_map(synonyms, synfile_type_map_path)
    except subprocess.CalledProcessError as e:
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


