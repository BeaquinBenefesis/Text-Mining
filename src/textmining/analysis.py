from typing import Iterator
from itertools import groupby, combinations
from collections import Counter, defaultdict
from textmining.models import CandidateHit, NormalizedHit, HitType, Association, CoOccurence
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
    def extract_cooccurrences(hits: Iterator[NormalizedHit]) -> Iterator[CoOccurence]:
        for sentence_id, sentence_hits in Grouper.group_by_sentence(hits):
            if len(sentence_hits) < 2:
                continue
            yield from (CoOccurence(article_id=hit_a.article_id,
                                    sentence_id=sentence_id,
                                    section_num=hit_a.section_num,
                                    entity_types=(hit_a.entity_type, hit_b.entity_type),
                                    entity_ids=(hit_a.entity_id, hit_b.entity_id)) 
                        for hit_a, hit_b in Grouper.extract_valid_combinations(sentence_hits))

                    

class EvidenceAggregator:
    
    def __init__(self):
        self.associations: dict[tuple[str, str], Association] = {}
    
    def record_coccurrence(self, cooc: CoOccurence) -> None:
        assoc = self.associations.setdefault(
            cooc.entity_ids,
            Association(entity_ids=cooc.entity_ids,
                        entity_types=cooc.entity_types,)
        )
        assoc.record_cooccurrence(cooc)
