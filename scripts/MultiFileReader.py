class MultiFileReader:

    def __init__(self, file_paths):
        self.handlers = {}
        self.index = {}
        for path in file_paths:
            self.handlers[path] = open(path, 'rb')
            self.index[path] = self._index_file(path)

    def _index_file(file_path):
        index = []
        offset = 0
        print(f'Indexing file: {file_path}')
        with open(file_path, 'rb') as f:
            for line in f:
                index.append(offset)
                offset += len(line)
        return index

    def close(self):
        for handler in self.handlers.values:
            handler.close()