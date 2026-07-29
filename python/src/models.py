from dataclasses import dataclass, field, replace
from typing import Optional
from enum import Enum
from .sentence_utils import parse_sentence_id
from natsort import natsort_key




class HitStatus(str, Enum):
    DEFAULT = 'DEFAULT' # No disambiguation performed
    EXACT = 'EXACT'
    RESOLVED = 'RESOLVED'
    AMBIGUOUS = 'AMBIGUOUS'
    FAILURE = 'FAILURE'

class HitType(str, Enum):
    MIR = 'MIR'
    TAXON = 'TAXON'
    DISEASE = 'DISEASE'
    TISSUE = 'TISSUE'
    CELL = 'CELL'
    PATHWAY = 'PATHWAY'
    DEFAULT = 'DEFAULT'

class SynonymType(str, Enum):
    STANDARD = 'STANDARD'
    ABBREVIATION = 'ABBREVIATION'
    INFERRED_ABBREVIATION = 'INFERRED_ABBREVIATION'
    UNKNOWN = 'UNKNOWN'

@dataclass
class NormalizedHit:
    entity_type: HitType
    synonym_type: SynonymType
    sentence_id: str
    synonym_id: str
    raw_text: str
    start_position: int
    hit_length: int
    synonym: str
    prefix: str
    suffix: str
    article_id: str = field(init=False)
    hit_status: HitStatus = HitStatus.DEFAULT
    normalization: Optional['NormalizationResult'] = None
    
    def __post_init__(self):
            self.article_id, self.section_num, self.sentence_num = parse_sentence_id(self.sentence_id)
            sent_sort_key = natsort_key(self.sentence_id)
            self.sort_key = (sent_sort_key, self.start_position, self.hit_length)
            
    def copy(self, **changes):
        return replace(self, **changes)
    
    @staticmethod
    def overlap(hit_1: 'NormalizedHit', hit_2: 'NormalizedHit'):
        if hit_1.sentence_id != hit_2.sentence_id:
            return False
        end_pos_1 = hit_1.start_position + hit_1.hit_length
        end_pos_2 = hit_2.start_position + hit_2.hit_length
        return max(hit_1.start_position, hit_2.start_position) < min(end_pos_1, end_pos_2)

class HitGroup:
    
    def __init__(self):
        self.hits: list[NormalizedHit] = []
        self.ids: set[str] = set()
        self.contains_abbreviations = False

    def add_hit(self, hit: NormalizedHit):
        self.hits.append(hit)
        self.ids.add(hit.synonym_id)
        if hit.synonym_type == SynonymType.ABBREVIATION:
            self.contains_abbreviations = True
    
    def is_ambiguous(self):
        return self.ids != 1
    
    def get_first(self):
        if len(self.hits) == 0:
            return None
        return self.hits[0]
    


class NormalizationStatus(str, Enum):
    NORMALIZED = 'NORMALIZED' # Successful exact normalization
    FALLBACK = 'FALLBACK' # Normalized using a fallback heuristic
    #AMBIGUOUS = 'AMBIGUOUS' # Normalization matched multiple entities
    UNRESOLVED = 'UNRESOLVED' # Could not normalize
    FILTERED = 'FILTERED' # Probably a false positive, filter out
    IN_BLACKLIST = 'IN_BLACKLIST' # Known terms of high ambiguity, low confidence hit

class NormalizationTargetType(str, Enum):
    MIR_FAMILY = 'MIR_FAMILY'
    MIR_PRECURSOR = 'MIR_PRECURSOR'
    MIR_MATURE = 'MIR_MATURE'

@dataclass
class NormalizationResult:
    status: NormalizationStatus
    normalized_id: Optional[str] = None
    target_type: Optional['NormalizationTargetType'] = None
    dead: bool = False


@dataclass(frozen=True)
class Association:
    sentence_id: str
    entity_ids: tuple[str, str]
    entity_types: tuple[HitType, HitType]


class Article:
    pass
    