from typing import Iterator
from itertools import groupby, combinations
from collections import Counter
from textmining.models import CandidateHit, NormalizedHit, HitType, Association
from textmining.normalization import normalized_successfully

class Grouper:
    
    @staticmethod
    def group_by_sentence(hits: Iterator[CandidateHit]) -> Iterator[tuple[str, list[NormalizedHit]]]:
        for sentence_id, group in groupby(hits, key=lambda h: h.sentence_id):
            yield sentence_id, list(group)
    
    
    @staticmethod    
    def overlapping_pair(hit_a: CandidateHit, hit_b: CandidateHit) -> bool:
        end_a = hit_a.start_position + hit_a.hit_length
        end_b = hit_b.start_position + hit_b.hit_length
        return hit_a.start_position < end_b and hit_b.start_position < end_a
    
    @staticmethod
    def valid_types(type_a: HitType, type_b: HitType) -> bool:
        return (type_a != type_b) and (type_a == HitType.MIR or type_b == HitType.MIR)
    
    @staticmethod
    def extract_valid_combinations(sentence_hits: list[NormalizedHit]) -> Iterator[tuple[NormalizedHit, NormalizedHit]]:
        for hit_a, hit_b in combinations(sentence_hits, 2):
            type_a = hit_a.entity_type
            type_b = hit_b.entity_type
            if not Grouper.valid_types(type_a, type_b):
                continue
            if not normalized_successfully(hit_a) or not normalized_successfully(hit_b):
                continue
            if Grouper.overlapping_pair(hit_a, hit_b):
                continue
            yield (hit_a, hit_b) if hit_a.entity_type == HitType.MIR else (hit_b, hit_a)
    
    @staticmethod
    def extract_cooccurrences(hits: Iterator[NormalizedHit]) -> Iterator[tuple[str, NormalizedHit, NormalizedHit]]:
        for sentence_id, sentence_hits in Grouper.group_by_sentence(hits):
            if len(sentence_hits) < 2:
                continue
            for (hit_a, hit_b) in Grouper.extract_valid_combinations(sentence_hits):      
                yield (sentence_id, hit_a, hit_b)        

class Analyzer:
    
    def __init__(self):
        pass
    
    def record_coocurrence(co_oc: tuple[str, NormalizedHit, NormalizedHit]):
        pass


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