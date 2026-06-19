import pandas as pd
from SynFileUtils import SynFileReader
import subprocess
import os
import tempfile


class HitsProcessor:
    _COL_NAMES = names=["sentence_id","synonym_id","matched_text","start_position","hit_length","synonym","prefix","suffix"]

    def __init__(self, hits_path, *synonym_paths, synfile_map, low_memory=False):
        self.hits_path = hits_path
        self.synonym_paths = synonym_paths
        self.low_memory = low_memory

    def get_hits_df(self, remove_sent_id_prefix=False, append_article_id=False, quoting=3) -> pd.DataFrame:
        df = pd.read_csv(self.hits_path, sep='\t', names=self._COL_NAMES, quoting=quoting)
        
        if remove_sent_id_prefix:
            df['sentence_id'] = df['sentence_id'].str.split(':').str[1]

        with SynFileReader(self.synonym_path, self.low_memory) as reader:
            
            split_values = df["synonym_id"].str.split(":").str[1]
            line_numbers = split_values.astype(int)
            
            if not self.low_memory:
                syn_series = pd.Series(reader.id_list)
                df['synonym_id'] = line_numbers.map(syn_series)
            else:
                unique_lines = line_numbers.unique()
                mapping = {ln: reader.extract_id(ln) for ln in unique_lines}
                df['synonym_id'] = line_numbers.map(mapping)  
                     
        if append_article_id:
            df['article_id'] = df['sentence_id'].str.split('.').str[0]
            
        return df
        

    def get_hits(self, remove_sent_id_prefix=False, append_article_id=False, sort=False):
        if sort:
            sorted_fd, sorted_path = tempfile.mkstemp()
            os.close(sorted_fd)
            try:
                 subprocess.run(['sort', '-V', self.hits_path, '-o', sorted_path], 
                                check=True, 
                                capture_output=True,
                                text=True)
                 yield(self._iter_hits(sorted_path, remove_sent_id_prefix, append_article_id))
            finally:
                 os.remove(sorted_path)
                  
        else:
             return self._iter_hits(remove_sent_id_prefix, append_article_id)
    
    def _iter_hits(self, hits_path, remove_sent_id_prefix=False, append_article_id=False):
        with SynFileReader(self.synonym_path, self.low_memory) as reader:
                    with open(hits_path, 'r') as f:
                        for line in f:
                            parts = dict(zip(self._COL_NAMES, line.split('\t')))
                            if remove_sent_id_prefix:
                                parts['sentence_id'] = parts['sentence_id'].split(':')[1]
                            line_number = int(parts['synonym_id'].split(':')[1])
                            parts['synonym_id'] = reader.extract_id(line_number)
                            if append_article_id:
                                parts['article_id'] = parts['sentence_id'].split('.')[0]
                            yield parts
    
    def _parse_synfile_map(path) -> dict:
            map = {}
            with open(path, 'r') as f:
                 for line in f:
                    line = line.strip()
                    synfile_path, synfile_id = line.split('\t')
                    map[synfile_id] = synfile_path