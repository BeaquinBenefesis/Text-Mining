import mmap
import time
import logging
from typing import Iterator
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)

def write_syn_file(output: str | Path,
                   synonym_groups: Iterator[tuple[str, list[str]]]):
    with open(output, 'w') as out:
        for group in synonym_groups:
            line = create_syn_line(group)
            out.write(line)
            out.write('\n')


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
    LINNAEUS-derived files), simply have no entry here."""
    output_path: Path
    abbreviation_output_path: Path
    roots: list[str] | None = None
