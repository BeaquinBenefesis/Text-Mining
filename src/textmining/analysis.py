from typing import Iterator
from itertools import groupby, combinations
from collections import Counter
from textmining.models import CandidateHit, NormalizedHit, NormalizationStatus, HitType, Association

class Grouper:
    
    def __init__(self):
        self.history = GrouperHistory()
    
    @staticmethod
    def group_by_sentence(hits: Iterator[CandidateHit]) -> Iterator[tuple[str, list[NormalizedHit]]]:
        for sentence_id, group in groupby(hits, key=lambda h: h.sentence_id):
            yield sentence_id, list(group)
    
    def valid_norm_status(self, hit: NormalizedHit) -> bool:
        if not hit.normalization:
            raise ValueError(f'Tried to group hit that was not normalized! Hit: {hit}')
        return hit.normalization.status not in (NormalizationStatus.UNRESOLVED, NormalizationStatus.FILTERED)
    
    @staticmethod    
    def overlapping_pair(hit_a: CandidateHit, hit_b: CandidateHit) -> bool:
        end_a = hit_a.start_position + hit_a.hit_length
        end_b = hit_b.start_position + hit_b.hit_length
        return hit_a.start_position < end_b and hit_b.start_position < end_a
    
    @staticmethod
    def valid_types(type_a: HitType, type_b: HitType) -> bool:
        return (type_a != type_b) and (type_a == HitType.MIR or type_b == HitType.MIR)
    
    def extract_valid_combinations(self, sentence_hits: list[NormalizedHit]) -> Iterator[tuple[NormalizedHit, NormalizedHit]]:
        for hit_a, hit_b in combinations(sentence_hits, 2):
            type_a = hit_a.entity_type
            type_b = hit_b.entity_type
            if not self.valid_types(type_a, type_b):
                continue
            if not self.valid_norm_status(hit_a) or not self.valid_norm_status(hit_b):
                continue
            if self.overlapping_pair(hit_a, hit_b):
                continue
            yield (hit_a, hit_b) if hit_a.entity_type == HitType.MIR else (hit_b, hit_a)
            
    def extract_cooccurrences(self, hits: Iterator[NormalizedHit], print_summary=True) -> Iterator:
        for sentence_id, sentence_hits in self.group_by_sentence(hits):
            if len(sentence_hits) < 2:
                continue
            for (hit_a, hit_b) in self.extract_valid_combinations(sentence_hits):      
                hit_a_id = hit_a.normalization.normalized_id
                hit_b_id = hit_b.normalization.normalized_id
                
                hit_a_type = hit_a.entity_type
                hit_b_type = hit_b.entity_type
                
                hit_a_score = hit_a.score
                hit_b_score = hit_b.score
                
                article_id = hit_a.article_id
                section_num = hit_a.section_num
                
                association = Association(article_id=article_id,
                                          sentence_id=sentence_id, 
                                          section_num=section_num,
                                          entity_ids=(hit_a_id, hit_b_id),
                                          entity_types=(hit_a_type, hit_b_type),
                                          entity_scores=(hit_a_score, hit_b_score))
                self.history.record(association)
                yield association
        if print_summary:
            self.history.print_most_common()

class Analyzer:
    
    def __init__(self):
        self.counts: Counter = Counter()
        
    def __init__(self):
            self.counts: Counter = Counter()
            self.total = 0
            
    def record(self, association: Association):
        self.total += 1
        key = (association.entity_ids, association.entity_types)
        self.counts[key] += 1
            
    def process_associations(self, associations: Iterator[Association]):
        for assoc in associations:
            self.record(assoc)
            #yield assoc
        
        

class GrouperHistory:

    def __init__(self):
        self.counts: Counter = Counter()
        self.total = 0

    def record(self, association: Association):
        self.total += 1
        key = (association.entity_ids, association.entity_types)
        self.counts[key] += 1

    def record_all(self, associations: Iterator[Association]) -> Iterator[Association]:
        # pass-through so you can log while still consuming the stream downstream
        for assoc in associations:
            self.record(assoc)
            yield assoc

    def print_most_common(self, top_n: int = 50):
        print(f"{'--- Top MIR-Entity Associations ---':^50}")
        print(f"Total associations recorded: {self.total}")
        print(f"Unique entity pairs:         {len(self.counts)}")
        for (entity_ids, entity_types), count in self.counts.most_common(top_n):
            id_mir, id_other = entity_ids
            type_mir, type_other = entity_types
            print(f"  {type_mir}:{id_mir}  <->  {type_other}:{id_other}  : {count}")