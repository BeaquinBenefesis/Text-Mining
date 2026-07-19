from dataclasses import dataclass, field, replace
from typing import Optional
from enum import Enum

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
    
@dataclass
class NormalizedHit:
    entity_type: HitType
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
            self.article_id = self.sentence_id.split('.', 1)[0]
            
    def copy(self, **changes):
        return replace(self, **changes)

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
    