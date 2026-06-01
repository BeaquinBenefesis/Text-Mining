import re

class SynFileReader:
    def __init__(self, file_path):
        self.file_path = file_path
        self.file = None
        self.index = None
        self.id_pattern = re.compile(r"^(?:([a-zA-Z0-9]+):)?([a-zA-Z0-9]+)")

    
    def __enter__(self):
        self.file = open(self.file_path, 'rb')
        self.index = self._index_file(self.file_path)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.file:
            self.file.close()


    def _index_file(self, file_path):
        index = []
        offset = 0
        with open(file_path, 'rb') as f:
            for line in f:
                index.append(offset)
                offset += len(line)
        return index
    
    def read_line(self, line_num: int) -> str:
        if line_num >= len(self.index):
            raise IndexError("Line number out of bounds.")

        # Seek to the byte offset of the target line
        self.file.seek(self.index[line_num])
        # Read the line and decode from bytes to string
        return self.file.readline().decode("utf-8")
    
    def extract_id(self, line_num) -> str:
        match = self.id_pattern.match(self.read_line(line_num))
        if match:
            prefix, num_id = match.groups()
            if prefix:
                return f"{prefix}:{num_id}"
            return num_id
        return None
        
    