import mmap
from collections import defaultdict

class SynFileReader:
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
    
def compute_ambisyn_dict(*args) -> dict:
    flipped = defaultdict(set)
    for path in args:
        for term_id, terms in get_syn_line_terms(path):
            for term in terms:
                flipped[term].add(term_id)
    
    ambisyn = {term: term_ids for term, term_ids in flipped.items() if len(term_ids) > 1}
    return ambisyn


def get_syn_line_terms(path):
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            term_id, terms = line.split(':', 1)
            yield term_id.strip(), [t.strip() for t in terms.split('|') if t.strip()]
