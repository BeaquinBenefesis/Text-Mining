import mmap
import os
from collections import defaultdict, Counter
from typing import Iterator
from pathlib import Path

def read_synfile(file) -> defaultdict:
    line_count = 0
    syn_count = 0
    out = defaultdict(set)
    all_terms_counter = Counter()
    
    with open(file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            
            syn_id, syns_raw = line.split(':', 1)
            syns = syns_raw.split('|')
            
            out[syn_id].update(syns)
            all_terms_counter.update(syns)
            
            line_count += 1
            syn_count += len(syns)
            
    print(f'{os.path.basename(file)}: Read {line_count} lines with {syn_count} terms.')
    
    duplicates = {term: count for term, count in all_terms_counter.items() if count > 1}
    
    if duplicates:
        print("\nTerms appearing more than once:")
        for term, count in sorted(duplicates.items(), key=lambda x: x[1], reverse=True):
            print(f"  '{term}': {count} times")
    else:
        print("\nNo duplicate terms found.")
            
    return out

def compare_synfiles(file_1, file_2, print_overlapping=False):
    dict_1 = read_synfile(file_1)
    dict_2 = read_synfile(file_2)
    
    ids_1 = set(dict_1.keys())
    ids_2 = set(dict_2.keys())
    
    terms_1 = {term.lower() for synonyms in dict_1.values() for term in synonyms}
    terms_2 = {term.lower() for synonyms in dict_2.values() for term in synonyms}
    
    print(f'{os.path.basename(file_1)}: {len(ids_1)} unique ids with {len(terms_1)} unique synonyms')
    print(f'{os.path.basename(file_2)}: {len(ids_2)} unique ids with {len(terms_2)} unique synonyms')
    
    overlapping_ids = ids_1 & ids_2
    overlapping_terms = terms_1 & terms_2
    print(f'Number of overlapping ids: {len(overlapping_ids)}')
    print(f'Number of overlapping terms: {len(overlapping_terms)}')
    
    if print_overlapping:
        out_id = "\n".join((overlapping_ids))
        out_term = "\n".join((overlapping_terms))
        print(f'Overlapping ids: {out_id}')
        print(f'Overlapping terms: {out_term}')

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
        print(f'Indexing: {self.file_path}')
        self.index = [0]
        pos = self.mm.find(b'\n')
        while pos != -1:
            self.index.append(pos + 1)
            pos = self.mm.find(b'\n', pos + 1)
        # Remove trailing offset if file ends with a newline
        if self.index[-1] >= self.mm.size():
            self.index.pop()

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

# Normalize everything to lowercase    
def compute_ambisyn_dict(syn_paths) -> dict:
    flipped = defaultdict(set)
    for path in syn_paths:
        for term_id, terms in get_syn_line_terms(path):
            for term in terms:
                term = term.lower()
                flipped[term].add(term_id)
    
    ambisyn = {term: term_ids for term, term_ids in flipped.items() if len(term_ids) > 1}
    return ambisyn


def get_syn_line_terms(path):
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            term_id, terms = line.split(':', 1)
            yield term_id.strip(), [t.strip() for t in terms.split('|') if t.strip()]


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


def merge_synonyms(input_file, output_file):
    merged_data = defaultdict(set)

    # Step 1: Read and merge data
    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue

            # Split into ID and the synonyms string
            id_part, synonyms_part = line.split(":", 1)
            id_part = id_part.strip()

            # Split synonyms by '|' and add them to the set (removes duplicates)
            synonyms = [s.strip() for s in synonyms_part.split("|") if s.strip()]
            merged_data[id_part].update(synonyms)

    # Step 2: Write the merged data to the output file
    with open(output_file, "w", encoding="utf-8") as f:
        for id_part, synonyms_set in sorted(merged_data.items()):
            # Join synonyms back with '|'
            synonyms_string = "|".join(sorted(synonyms_set))
            f.write(f"{id_part}:{synonyms_string}\n")


basepath_in = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/taxonomy_bk/'
basepath_out = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/taxonomy_no_dups/'
file_names = ['linnaeus_cell_lines.syn', 'linnaeus_proxy.syn', 'linnaeus_species.syn']
synfile_paths_in = (basepath_in + file_name for file_name in file_names)
synfile_paths_out = (basepath_out + file_name for file_name in file_names)

for in_f, out_f in zip(synfile_paths_in, synfile_paths_out):
    merge_synonyms(in_f, out_f)
