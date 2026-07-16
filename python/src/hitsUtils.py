from SynFileUtils import MultiSynFileReader
from SynFileUtils import compute_ambisyn_dict
import subprocess
import os
import tempfile
from collections import deque
import json
import glob
from sentence_utils import check_sorted
from itertools import zip_longest
from dataclasses import dataclass, field
from NormUtils import NormalizationStatus
from typing import Iterator, Optional
from collections import Counter
from enum import Enum

_COL_NAMES = ["sentence_id","synonym_id","matched_text","start_position","hit_length","synonym","prefix","suffix"]

class HitsProcessor:

    def __init__(self, hits_path, synfile_map, synfile_type_map, low_memory=False):
        self.hits_path = hits_path
        self.low_memory = low_memory
        self.type_map = HitsProcessor.parse_synfile_type_map(synfile_type_map)
        self.synfile_map = HitsProcessor.parse_synfile_map(synfile_map)
        self.synonym_paths = self.synfile_map.values()
        self.file_id_to_type = {
            syn_id: self.type_map[os.path.basename(path)]
            for syn_id, path in self.synfile_map.items()
        }      

    def get_hits(self, sort=False, resolve_ambiguous=True, print_status=False):
        history = HitProcessorHistory(sort)
        if sort:
            sorted_fd, sorted_path = tempfile.mkstemp()
            os.close(sorted_fd)
            try:
                subprocess.run(
                    ['sort', '-t\t', '-k1,1V', '-k4,4n', self.hits_path, '-o', sorted_path],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                raw_hits = self._iter_hits(sorted_path)
                pipeline = (self._resolve_by_article(raw_hits) if resolve_ambiguous else raw_hits)
                for hit in pipeline:
                    history.update(hit)
                    yield hit
            finally:
                os.remove(sorted_path)
        else:
            raw_hits = self._iter_hits(sorted_path if sort else self.hits_path)
            pipeline = self._resolve_by_article(raw_hits) if resolve_ambiguous else raw_hits
            for hit in pipeline:
                history.update(hit)
                yield hit
        if print_status:
            history.print_summary()

    
    def _resolve_by_article(self, hits: Iterator['NormalizedHit']):
        global_ambisyns = compute_ambisyn_dict(self.synonym_paths)
        test_json = {key: list(val) for key, val in global_ambisyns.items()}
    
        with open('ambisyn.json', 'w') as test:
            json.dump(test_json, test, indent=3)
        
        hit_buffer = deque()
        prev_article = None
        prev_hit = None
        for hit in hits:
            if prev_hit and not check_sorted(prev_hit.sentence_id, prev_hit.start_position, hit.sentence_id, hit.start_position):
                raise ValueError(f"Hits are not sorted in article. Can not resolve ambiguous hits!"
                                 f"Previous hit: {prev_hit.sentence_id}, current hit: {hit.sentence_id}")
            current_article = hit.article_id
            if prev_article is not None and current_article != prev_article:
                yield from self._resolve_ambiguous_hits(hit_buffer, global_ambisyns)
                hit_buffer.clear()
            hit_buffer.append(hit)
            prev_article = current_article
            prev_hit = hit

        if hit_buffer:
            yield from self._resolve_ambiguous_hits(hit_buffer, global_ambisyns)

    

    def _resolve_ambiguous_hits(self, unprocessed_hits: deque['NormalizedHit'], global_ambisyns: dict) -> deque['NormalizedHit']:
        groups = []
        current_group = []
        prev_span = None
        unambiguous_ids = set()

        for hit in unprocessed_hits:
            synonym = hit.synonym.lower()
            is_ambiguous = synonym in global_ambisyns
            if not is_ambiguous:
                unambiguous_ids.add(hit.synonym_id)

            span = (hit.sentence_id, hit.start_position, hit.hit_length)
            if prev_span is not None and span != prev_span:
                groups.append(current_group)
                current_group = []
            current_group.append(hit)
            prev_span = span

        if current_group:
            groups.append(current_group)

        processed_hits = deque()

        hit: NormalizedHit
        for group in groups:
            # Default case, unambiguous mapping
            if len(group) == 1:
                hit = group[0]
                processed_hits.append(hit)
                hit.hit_status = HitStatus.DEFAULT
                continue

            possible_ids = global_ambisyns.get(group[0].synonym.lower(), set())
            intersection = possible_ids & unambiguous_ids

            if len(intersection) == 1:
                hit = group[0]
                hit.synonym_id = next(iter(intersection))
                hit.hit_status = HitStatus.RESOLVED
                processed_hits.append(hit)
            else:
                for hit in group:
                    hit.hit_status = HitStatus.AMBIGUOUS
                    processed_hits.append(hit)

        return processed_hits

        

    def _iter_hits(self, hits_path) -> Iterator['NormalizedHit']:
        '''Returns a stream of NormalizedHit objects.'''
        with MultiSynFileReader(self.low_memory) as reader:
            with open(hits_path, 'r') as f:
                for line in f:
                    line = line.rstrip('\n')
                    if not line:
                        continue
                    parts = dict(zip_longest(_COL_NAMES, [x.strip() for x in line.split('\t')], fillvalue=''))
                    file_id, line_number = parts['synonym_id'].split(':', 1)
                    if file_id not in self.synfile_map:
                        raise KeyError(f"No synonym file mapped for key: {file_id!r}")
                    file_path = self.synfile_map[file_id]
                    hit_type = self.file_id_to_type[file_id]
                                    
                    hit = NormalizedHit(entity_type=hit_type,
                                        sentence_id=parts['sentence_id'],
                                        synonym_id=reader.extract_id(file_path, int(line_number)),
                                        raw_text=parts['matched_text'],
                                        start_position=int(parts['start_position']),
                                        hit_length=int(parts['hit_length']),
                                        synonym=parts['synonym'],
                                        prefix=parts['prefix'],
                                        suffix=parts['suffix'])
                    
                    yield hit

    @staticmethod        
    def parse_synfile_map(path) -> dict:
            map = {}
            with open(path, 'r') as f:
                 for line in f:
                    line = line.strip()
                    synfile_path, synfile_id = line.split('\t')
                    map[synfile_id] = synfile_path
            return map
    
    @staticmethod
    def parse_synfile_type_map(path):
        result_map = {}
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:  # Skip empty lines if any
                    continue
                    
                synfile_path, synfile_type = line.split('\t')

                if synfile_type not in HitType.valid_types:
                    raise ValueError(f'Type {synfile_type} could not be recognized. Valid types are: {HitType.valid_types}')
                
                expanded_paths = glob.glob(synfile_path, recursive=True)
                
                if expanded_paths:
                    for matched_path in expanded_paths:
                        base_name = os.path.basename(matched_path)
                        if base_name in result_map:
                            raise ValueError(f'Conficting synonym file names: {base_name}')
                        result_map[base_name] = synfile_type
                else:
                    raise ValueError(f'Synonym file(s) {synfile_path} could not be found!')
        return result_map

class HitStatus(str, Enum):
    DEFAULT = 'DEFAULT'
    RESOLVED = 'RESOLVED'
    AMBIGUOUS = 'AMBIGUOUS'

class HitType(str, Enum):
    valid_types = set(['MIR', 'TAXON', 'DISEASE'])
    MIR = 'MIR'
    TAXON = 'TAXON'
    DISEASE = 'DISEASE'
    
@dataclass
class NormalizedHit:
    entity_type: str
    sentence_id: str
    synonym_id: str
    raw_text: str
    start_position: int
    hit_length: int
    synonym: str
    prefix: str
    suffix: str
    article_id: str = field(init=False)
    normalized_id: Optional[str] = None
    hit_status: Optional[str] = None
    normalization_status: Optional[NormalizationStatus] = None
    
    def __post_init__(self):
            self.article_id = self.sentence_id.split('.', 1)[0]

class HitProcessorHistory:    
    def __init__(self, sorted: bool, performed_disambiguation: bool):
        self.hits_processed = 0
        self.sorted = sorted
        self.types_processed = Counter()
        self.hit_statuses = Counter()
        self.performed_disambiguation = performed_disambiguation
    
    def update(self, hit: NormalizedHit):
        self.hits_processed += 1
        self.types_processed[hit.entity_type] += 1
        if self.performed_disambiguation:
            self.hit_statuses.update(hit.hit_status)
    
    def print_summary(self):
        print(f"{'--- Processing Summary ---':^30}")
        print(f"Total Hits Processed: {self.hits_processed}")
        print(f"Sorted State:        {self.sorted}")
        
        print("\nBreakdown by Entity Type:")
        for entity, count in self.types_processed.items():
            print(f"  {entity:<15}: {count}")
        if self.performed_disambiguation:
            print("\nBreakdown by Hit Status:")
            for status, count in self.hit_statuses.items():
                print(f"  {status:<15}: {count}")