from dataclasses import dataclass, field, replace
from typing import Optional
from enum import Enum
from src.sentence_utils import parse_sentence_id
from natsort import natsort_key
from collections import defaultdict

class GroupStatus(str, Enum):
    DEFAULT = 'DEFAULT' # No disambiguation performed
    EXACT_MATCH = 'EXACT_MATCH'
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

class SynonymType(str, Enum):
    STANDARD = 'STANDARD'
    ABBREVIATION = 'ABBREVIATION'
    INFERRED_ABBREVIATION = 'INFERRED_ABBREVIATION'

@dataclass
class CandidateHit:
    entity_type: HitType
    synonym_type: SynonymType
    sentence_id: str
    entity_id: str
    raw_text: str
    start_position: int
    hit_length: int
    synonym: Optional[str] = None
    prefix: Optional[str] = None
    suffix: Optional[str] = None
    synonym_id: Optional[str] = None
    mention_type: Optional[str] = None# This is used for gold standard hits from NCBI
    article_id: str = field(init=False)
    section_num: str = field(init=False)
    sentence_num: str = field(init=False)
    sort_key: tuple = field(init=False, repr=False)
    
    def __post_init__(self):
            self.article_id, self.section_num, self.sentence_num = parse_sentence_id(self.sentence_id)
            sent_sort_key = natsort_key(self.sentence_id)
            self.sort_key = (sent_sort_key, self.start_position, self.hit_length)
            
    def copy(self, **changes):
        return replace(self, **changes)

class HitGroup:
    def __init__(self):
        self.hits: list[CandidateHit] = []
        self.ids: set[str] = set()
        self.group_status: GroupStatus = GroupStatus.DEFAULT

    def add_hit(self, hit: CandidateHit):
        self.hits.append(hit)
        self.ids.add(hit.entity_id)
    
    def is_ambiguous(self) -> bool:
        return len(self.ids) > 1
    
    def get_first(self) -> Optional[CandidateHit]:
        if not self.hits:
            return None
        return self.hits[0]

    def contains_abbreviation(self) -> bool:
        return any(h.synonym_type == SynonymType.ABBREVIATION for h in self.hits)

    def contains_inferred_abbreviation(self) -> bool:
        return any(h.synonym_type == SynonymType.INFERRED_ABBREVIATION for h in self.hits)

    def contains_any_abbreviation(self) -> bool:
        return any(
            h.synonym_type in (SynonymType.ABBREVIATION, SynonymType.INFERRED_ABBREVIATION)
            for h in self.hits
        )
    
    def entity_type_set(self) -> set[HitType]:
        return {h.entity_typet for h in self.hits}
        
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


@dataclass
class NormalizedHit(CandidateHit):
    normalization: Optional[NormalizationResult] = None
    @classmethod
    def from_candidate(
        cls,
        candidate: CandidateHit,
        normalization: Optional['NormalizationResult'] = None,
        **changes
    ) -> 'NormalizedHit':
        return cls(
            entity_type=changes.get('entity_type', candidate.entity_type),
            synonym_type=changes.get('synonym_type', candidate.synonym_type),
            sentence_id=changes.get('sentence_id', candidate.sentence_id),
            synonym_id=changes.get('synonym_id', candidate.synonym_id),
            entity_id=changes.get('entity_id', candidate.entity_id),
            raw_text=changes.get('raw_text', candidate.raw_text),
            start_position=changes.get('start_position', candidate.start_position),
            hit_length=changes.get('hit_length', candidate.hit_length),
            synonym=changes.get('synonym', candidate.synonym),
            prefix=changes.get('prefix', candidate.prefix),
            suffix=changes.get('suffix', candidate.suffix),
            normalization=normalization)
        
class NormalizationContext:
    def __init__(self):
        self._buffers = defaultdict(list)
        self._taxon_cache = None
    
    def add_hit(self, hit: CandidateHit):
        self._buffers[hit.entity_type].append(hit)
    
    def hits_of(self, hit_type):
        return self._buffers.get(hit_type, [])
    
    def get_taxon_relevance(self):
        if self._taxon_cache:
            return self._taxon_cache
        tax_buffer = self._buffers[HitType.TAXON]
        relevance = {tax.entity_id : 1 for tax in tax_buffer}
        self._taxon_cache = relevance
        return relevance
    
    def clear(self):
        self._buffers = defaultdict(list)
        self._taxon_cache = None