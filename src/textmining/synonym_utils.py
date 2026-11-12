import mmap
import time
import logging
from typing import Iterator, Iterable
from collections import defaultdict
from pathlib import Path
from dataclasses import dataclass
from textmining.enums import SynonymScope

logger = logging.getLogger(__name__)

def write_syn_file(output: str | Path,
                   synonym_groups: Iterator[tuple[str, list[str]]]):
    with open(output, 'w') as out:
        for group in synonym_groups:
            line = create_syn_line(group)
            out.write(line)
            out.write('\n')


def drop_shadowed(triples: Iterable[tuple[str, list[str], list[str]]],
                  authoritative: Iterable[tuple[str, list[str], list[str]]]
                  ) -> tuple[list[tuple[str, list[str], list[str]]], list[tuple[str, str, str]]]:
    """what"""
    owners = defaultdict(set)
    for term_id, syns, _ in authoritative:
        for s in syns:
            owners[s.casefold()].add(term_id)

    kept_triples, dropped = [], []
    for term_id, syns, abbrevs in triples:
        kept = []
        for s in syns:
            name_owners = owners.get(s.casefold(), set())
            # a name that is authoritative for this term too stays, also when terms share it
            if name_owners and term_id not in name_owners:
                dropped.append((term_id, s, ','.join(sorted(name_owners))))
            else:
                kept.append(s)
        kept_triples.append((term_id, kept, abbrevs))
    return kept_triples, dropped


CASE_SENS_TAG = "@CASE_SENS"


def add_case_sensitivity(synonym: str) -> str:
    if len(synonym) < 8 and synonym.isascii() and synonym.isalpha():
        return synonym + CASE_SENS_TAG
    return synonym


def case_sensitive_abbreviations(abbrevs: list[str]) -> tuple[list[str], list[str]]:
    cased = {a.lower() for a in abbrevs if not a.islower()}
    kept = [a for a in abbrevs if not (a.islower() and a in cased)]
    dropped = [a for a in abbrevs if a.islower() and a in cased]
    return [add_case_sensitivity(a) for a in kept], dropped


def create_syn_line(id_to_syns: tuple[str, list[str]]):
    term_id, syns = id_to_syns
    return f"{term_id}:{'|'.join(syns)}"

class SynFileReader:
    """Provides efficient access to specific lines of a synonym file"""

    def __init__(self, file_path, low_memory=False):
        self.file_path = file_path
        self.low_memory = low_memory
        self.file = None
        self.id_list = None
        self.index = None
        self.mm = None

    def __enter__(self):
        if not self.low_memory:
            # Mode 1: Load everything into a list in RAM
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.id_list = [line.split(':')[0] for line in f]
            logger.debug('Loaded %d ids into memory for %s', len(self.id_list), self.file_path)
        else:
            # Mode 2: Low memory disk-seeking using fast OS-level mmap
            self.file = open(self.file_path, 'rb')
            self.mm = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
            self._index_file_fast()

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.mm:
            self.mm.close()
        if self.file:
            self.file.close()

    def _index_file_fast(self):
        """Uses mmap to find line endings at C-speed instead of Python loops."""
        start = time.time()
        self.index = [0]
        pos = self.mm.find(b'\n')
        while pos != -1:
            self.index.append(pos + 1)
            pos = self.mm.find(b'\n', pos + 1)
        # Remove trailing offset if file ends with a newline
        if self.index[-1] >= self.mm.size():
            self.index.pop()
        logger.info('Indexed %d lines for %s in %.2fs', len(self.index), self.file_path, time.time() - start)

    def extract_id(self, line_num: int) -> str:
        # Fast path: In-Memory
        if not self.low_memory:
            if line_num >= len(self.id_list):
                raise IndexError("Line number out of bounds.")
            return self.id_list[line_num]

        # Slow path: Disk-Seeking via mmap
        if line_num >= len(self.index):
            raise IndexError("Line number out of bounds.")

        self.mm.seek(self.index[line_num])
        # Read the line up to the newline byte
        line_bytes = self.mm.readline()
        line = line_bytes.decode('utf-8')
        return line.split(':')[0]

class MultiSynFileReader:
    """Manages multiple SynFileReader instances, keyed by file path."""

    def __init__(self, low_memory=False):
        self.low_memory = low_memory
        self._readers: dict[str, SynFileReader] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_all()

    def _get_reader(self, path: str) -> SynFileReader:
        reader = self._readers.get(path)
        if reader is None:
            logger.debug('Opening SynFileReader for %s', path)
            reader = SynFileReader(path, self.low_memory)
            reader.__enter__()
            self._readers[path] = reader
        return reader

    def extract_id(self, path: str, line_num: int) -> str:
        return self._get_reader(path).extract_id(line_num)

    def close_all(self):
        for reader in self._readers.values():
            reader.__exit__(None, None, None)
        self._readers.clear()


@dataclass(frozen=True)
class ExtractedSynonymSpec:
    """A synonym file that IS machine-extractable from its HitType's own
    ontology via OntologyGraph.extract_synonyms(roots)/extract_synonyms.py.
    Only used by refresh_data.py to know what to regenerate after an
    ontology rebuild. Synonym files
    with no clean root, or not derived from an .obo at all (e.g. TAXON's
    LINNAEUS-derived files), simply have no entry here.
    `scopes` are the OBO synonym scopes to extract; ontologies differ in
    which scope they file their usable synonyms under.
    The root terms themselves ("pathway", "cell", "disease") have an information
    content of 0 and are left out of the synonym files unless `include_roots`."""
    output_path: Path
    abbreviation_output_path: Path
    roots: list[str] | None = None
    scopes: tuple[SynonymScope, ...] = (SynonymScope.EXACT,)
    include_roots: bool = False
