from .SynFileUtils import MultiSynFileReader, compute_ambisyn_dict
import subprocess
import os
import tempfile
from collections import deque
import json
import glob
from itertools import zip_longest
from typing import Iterator
from collections import Counter
from .models import NormalizedHit, HitType, HitStatus, SynonymType, HitGroup
from dataclasses import dataclass, field

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
        self.history = HitProcessorHistory()      

    def get_hits(self, remove_sent_id_prefix=True, map_syn=True, sort=False, resolve_ambiguous=True, print_summary=True):
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
                raw_hits = self._iter_hits(hits_path=sorted_path,
                                           map_syn=map_syn,
                                           remove_sent_id_prefix=remove_sent_id_prefix)
                pipeline = (self._resolve_by_article(raw_hits) if resolve_ambiguous else raw_hits)
                yield from self._track_output(pipeline)
            finally:
                os.remove(sorted_path)
        else:
            raw_hits = self._iter_hits(self.hits_path, map_syn)
            pipeline = self._resolve_by_article(raw_hits) if resolve_ambiguous else raw_hits
            yield from self._track_output(pipeline)
        if print_summary:
            self.history.print_summary()

    def _track_output(self, pipeline: Iterator['NormalizedHit']):
        for hit in pipeline:
            self.history.record_output_hit(hit)
            yield hit
    
    def _resolve_by_article(self, hits: Iterator['NormalizedHit']):
        global_ambisyns = compute_ambisyn_dict(self.synonym_paths)
        test_json = {key: list(val) for key, val in global_ambisyns.items()}
    
        with open('ambisyn.json', 'w') as test:
            json.dump(test_json, test, indent=3)
        
        hit_buffer = deque()
        prev_article = None
        prev_hit = None
        for hit in hits:
            if prev_hit and not prev_hit.sort_key <= hit.sort_key:
                raise ValueError(f"Hits are not sorted. Can not resolve ambiguous hits! "
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
    
    # Find hits mapping to exactly the same positions
    @staticmethod   
    def _group_hits_by_span(unprocessed_hits: deque[NormalizedHit]) -> list[HitGroup]:
        groups = []
        current_group = HitGroup()
        prev_span = None
        for hit in unprocessed_hits:
            span = hit.sort_key
            if prev_span is not None and span != prev_span:
                groups.append(current_group)
                current_group = HitGroup()
            current_group.add_hit(hit)
            prev_span = span
        if current_group:
            groups.append(current_group)
        return groups
    
    # Returns a set of unambiguous synonym id hits, that did not come from an abbreviation hit
    @staticmethod
    def collect_unambiguous_ids(groups: list[HitGroup]) -> set:
        return set([g.get_first().synonym_id for g in groups 
                    if not g.is_ambiguous() and g.get_first().synonym_type != SynonymType.ABBREVIATION])
    
    def resolve_abbreviations(groups: list[HitGroup], unambiguous_ids: set) -> Iterator[NormalizedHit]:
        for g in groups:
            if not g.contains_abbreviations:
                continue
            for hit in g.hits:
                if hit.synonym_type == SynonymType.ABBREVIATION:
                    
    
    def _resolve_ambiguous_groups(groups: list[HitGroup], unambiguous_ids: set):
        processed_hits = deque()
        for g in groups:
            if not g.is_ambiguous():
                hit = g.get_first()
                processed_hits.append(hit)
                hit.hit_status = HitStatus.EXACT
                continue
            
            intersection = unambiguous_ids & g.ids
            if len(intersection) == 1:
                hit = g.get_first()
                hit.synonym_id = next(iter(intersection))
                hit.hit_status = HitStatus.RESOLVED
                processed_hits.append(hit)
            else:
                status = HitStatus.AMBIGUOUS if len(intersection) > 1 else HitStatus.FAILURE
                for hit in g.hits:
                    hit.hit_status = status
                    processed_hits.append(hit)
        return processed_hits
                
      
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

            span = hit.sort_key
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
                hit.hit_status = HitStatus.EXACT
                self.history.record_group(group)
                continue

            possible_ids = global_ambisyns.get(group[0].synonym.lower(), set())
            intersection = possible_ids & unambiguous_ids
            self.history.record_group(group, intersection_size=len(intersection))

            if len(intersection) == 1:
                # Resolved case
                hit = group[0]
                hit.synonym_id = next(iter(intersection))
                hit.hit_status = HitStatus.RESOLVED
                processed_hits.append(hit)
            else:
                status = HitStatus.AMBIGUOUS if len(intersection) > 1 else HitStatus.FAILURE
                # Could not resolve
                for hit in group:
                    hit.hit_status = status
                    processed_hits.append(hit)

        return processed_hits

        

    def _iter_hits(self, hits_path, map_syn=True, remove_sent_id_prefix=True) -> Iterator['NormalizedHit']:
        '''Returns a stream of NormalizedHit objects.'''
        with MultiSynFileReader(self.low_memory) as reader:
            with open(hits_path, 'r') as f:
                for line in f:
                    line = line.rstrip('\n')
                    if not line:
                        continue
                    parts = dict(zip_longest(_COL_NAMES, [x.strip() for x in line.split('\t')], fillvalue=''))
                    
                    synonym_id = parts['synonym_id']
                    hit_type = HitType.DEFAULT
                    synonym_type = SynonymType.UNKNOWN
                    
                    if map_syn:
                        file_id, line_number = parts['synonym_id'].split(':', 1)
                        if file_id not in self.synfile_map:
                            raise KeyError(f"No synonym file mapped for key: {file_id!r}")
                        file_path = self.synfile_map[file_id]
                        hit_type, is_abbrev = self.file_id_to_type[file_id]
                        synonym_id = reader.extract_id(file_path, int(line_number))
                        synonym_type = SynonymType.ABBREVIATION if is_abbrev else SynonymType.STANDARD
                
                    sentence_id = parts['sentence_id'].split(':', 1)[1] if remove_sent_id_prefix else parts['sentence_id']
                                    
                    hit = NormalizedHit(entity_type=hit_type,
                                        synonym_type=synonym_type,
                                        sentence_id=sentence_id,
                                        synonym_id=synonym_id,
                                        raw_text=parts['matched_text'],
                                        start_position=int(parts['start_position']),
                                        hit_length=int(parts['hit_length']),
                                        synonym=parts['synonym'],
                                        prefix=parts['prefix'],
                                        suffix=parts['suffix'])
                    self.history.record_input_hit(hit)
                    
                    yield hit

    @staticmethod        
    def parse_synfile_map(path) -> dict:
        map = {}
        if not path:
            return map
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                synfile_path, synfile_id = line.split('\t')
                map[synfile_id] = synfile_path
        return map
    
    @staticmethod
    def parse_synfile_type_map(path):
        result_map = {}
        if not path:
            return map
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:  # Skip empty lines if any
                    continue
                    
                synfile_path, synfile_type, is_abbrev = line.split('\t')
                
                expanded_paths = glob.glob(synfile_path, recursive=True)
                
                if expanded_paths:
                    for matched_path in expanded_paths:
                        base_name = os.path.basename(matched_path)
                        if base_name in result_map:
                            raise ValueError(f'Conficting synonym file names: {base_name}')
                        result_map[base_name] = (HitType(synfile_type), is_abbrev)
                else:
                    raise ValueError(f'Synonym file(s) {synfile_path} could not be found!')
        return result_map

@dataclass
class HitProcessorHistory:
    input_hits: int = 0
    output_hits: int = 0
    groups: int = 0
    multi_candidate_groups: int = 0
    groups_size_counts: Counter = field(default_factory=Counter)
    hit_statuses: Counter = field(default_factory=Counter)
    per_type_input_hits: Counter = field(default_factory=Counter)
    per_type_output_hits: Counter = field(default_factory=Counter)
    dictionary_ambiguous_synonyms: Counter = field(default_factory=Counter)
    unresolved_synonyms: Counter = field(default_factory=Counter)
    resolved_synonyms: Counter = field(default_factory=Counter)

    def record_input_hit(self, hit: NormalizedHit):
        self.input_hits += 1
        self.per_type_input_hits[hit.entity_type] += 1

    def record_output_hit(self, hit: NormalizedHit):
        self.output_hits += 1
        self.per_type_output_hits[hit.entity_type] += 1
        self.hit_statuses[hit.hit_status] += 1

    def record_group(self, group: list['NormalizedHit'], intersection_size: int = None):
        size = len(group)
        self.groups += 1
        self.groups_size_counts[size] += 1
        if size == 1:
            return

        self.multi_candidate_groups += 1
        synonym = group[0].synonym.lower()
        self.dictionary_ambiguous_synonyms[synonym] += 1

        if intersection_size == 1:
            self.resolved_synonyms[synonym] += 1
        else:
            self.unresolved_synonyms[synonym] += 1

    @property
    def hits_collapsed(self) -> int:
        return self.input_hits - self.output_hits

    def print_summary(self, top_n: int = 15):
        print(f"{'--- Hit Processor Summary ---':^40}")
        print(f"Input hits:                 {self.input_hits}")
        print(f"Output hits:                {self.output_hits}")
        print(f"Hits collapsed:             {self.hits_collapsed}")
        print(f"Spans / groups:             {self.groups}")
        print(f"  Multi-candidate groups:   {self.multi_candidate_groups}")

        resolved = sum(self.resolved_synonyms.values())
        if self.multi_candidate_groups:
            print(f"  Resolution rate:          {resolved/self.multi_candidate_groups:.1%} "
                  f"({resolved}/{self.multi_candidate_groups})")

        print("\nGroup size distribution:")
        for size, count in sorted(self.groups_size_counts.items()):
            print(f"  {size} candidates: {count} groups")

        print("\nInput hits by entity type:")
        for entity, count in self.per_type_input_hits.items():
            print(f"  {entity:<20}: {count}")

        print("\nOutput hits by entity type:")
        for entity, count in self.per_type_output_hits.items():
            print(f"  {entity:<20}: {count}")

        print("\nOutput hits by status:")
        for status, count in self.hit_statuses.items():
            print(f"  {status:<20}: {count}")

        print(f"\nTop {top_n} synonyms flagged ambiguous by the dictionary:")
        for synonym, count in self.dictionary_ambiguous_synonyms.most_common(top_n):
            print(f"  {synonym:<30}: {count}")

        print(f"\nTop {top_n} synonyms most often successfully resolved:")
        for synonym, count in self.resolved_synonyms.most_common(top_n):
            print(f"  {synonym:<30}: {count}")

        print(f"\nTop {top_n} synonyms remaining unresolved:")
        for synonym, count in self.unresolved_synonyms.most_common(top_n):
            print(f"  {synonym:<30}: {count}")
            
