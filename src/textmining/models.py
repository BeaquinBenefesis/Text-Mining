from dataclasses import dataclass, field, replace
from typing import Optional
from collections import defaultdict
from textmining.scoring import HitScore
from textmining.sentence_utils import parse_sentence_id
from textmining.enums import HitType, SynonymType, GroupStatus, NormalizationStatus, NormalizationTargetType
from textmining.scoring import section_weigth
from math import log2


@dataclass(kw_only=True)
class CandidateHit:
    entity_type: HitType
    synonym_type: SynonymType
    sentence_id: str
    entity_id: str
    raw_text: str
    start_position: int
    hit_length: int
    prefix: str = None
    suffix: str = None
    origin_file_name: Optional[str] = None
    synonym: Optional[str] = None
    synonym_id: Optional[str] = None
    mention_type: Optional[str] = None  # This is used for gold standard hits from NCBI
    article_id: str = field(init=False)
    section_num: int = field(init=False)
    sentence_num: int = field(init=False)
    sort_key: tuple = field(init=False, repr=False)
    
    def __post_init__(self):
            self.article_id, self.section_num, self.sentence_num = parse_sentence_id(self.sentence_id)
            self.sort_key = (self.article_id, self.section_num, self.sentence_num, self.start_position, self.hit_length)
            
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
        return {h.entity_type for h in self.hits}
        
@dataclass
class NormalizationResult:
    status: NormalizationStatus
    normalized_id: Optional[str] = None
    target_type: Optional['NormalizationTargetType'] = None
    dead: bool = False


@dataclass
class CoOccurence:
    article_id: str
    sentence_id: str
    section_num: str
    entity_ids: tuple[str, str]
    entity_types: tuple[HitType, HitType]
    
    @property
    def score(self):
        return 1 * section_weigth(self.section_num)


@dataclass
class AssociationEvidence:
    _current_article_id: Optional[str] = None
    _current_article_sum: float = 0.0
    _corpus_sum: float = 0.0
    
    def record_cooccurrence(self, cooccurrence: CoOccurence):
        if self._current_article_id and self._current_article_id > cooccurrence.article_id:
            raise ValueError(f'Unsorted article order: {self._current_article_id}, {cooccurrence.article_id}')
        if self._current_article_id != cooccurrence.article_id:
            self._flush_article_evidence()
            self._current_article_id = cooccurrence.article_id
        self._current_article_sum += cooccurrence.score
        
    def _flush_article_evidence(self):
        if self._current_article_id is not None:
            self._corpus_sum += log2(1 + self._current_article_sum)
        self._current_article_sum = 0.0
    
    @property
    def score(self):
        pending = log2(1 + self._current_article_sum)
        return log2(1 + self._corpus_sum + pending)


@dataclass
class Association:
    entity_ids: tuple[str, str]
    entity_types: tuple[HitType, HitType]
    evidence: AssociationEvidence = field(default_factory=lambda: AssociationEvidence())

    def record_cooccurrence(self, cooccurrence: CoOccurence):
        self.evidence.record_cooccurrence(cooccurrence)
    
    @property
    def score(self):
        return self.evidence.score
        
@dataclass(kw_only=True)
class NormalizedHit(CandidateHit):
    normalization: NormalizationResult
    score: Optional[HitScore] = None
    @classmethod
    def from_candidate(
        cls,
        candidate: CandidateHit,
        normalization: NormalizationResult,
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
            origin_file_name=changes.get('origin_file_name', candidate.origin_file_name),
            normalization=normalization)
    
    def to_dict(self) -> dict:
        return {
            "sentence_id": self.sentence_id,
            "entity_type": self.entity_type.name if self.entity_type else None,
            "synonym_type": self.synonym_type.name if self.synonym_type else None,
            "synonym_id": self.synonym_id,
            "entity_id": self.entity_id,
            "raw_text": self.raw_text,
            "start_position": self.start_position,
            "hit_length": self.hit_length,
            "synonym": self.synonym,
            "prefix": self.prefix,
            "suffix": self.suffix,
            "norm_status": self.normalization.status.name if self.normalization.status else None,
            "normalized_id": self.normalization.normalized_id,
            "target_type": self.normalization.target_type.name if self.normalization.target_type else None,
            "dead": self.normalization.dead,
            "score": f"{float(self.score.ic):.2f}" if self.score is not None and self.score.ic is not None else None,
        }
        
class NormalizationContext:
    def __init__(self, fetch_article):
        self._buffers = defaultdict(list)
        self._taxon_cache = None
        self._fetch_article = fetch_article
        self._article_cache = None
    
    def add_hit(self, hit: CandidateHit):
        self._buffers[hit.entity_type].append(hit)
    
    def hits_of(self, hit_type):
        return self._buffers.get(hit_type, [])
    
    def get_taxon_relevance(self):
        if self._taxon_cache is not None:
            return self._taxon_cache
        tax_buffer = self._buffers[HitType.TAXON]
        relevance = {tax.entity_id : 1 for tax in tax_buffer}
        self._taxon_cache = relevance
        return relevance
    
    def fetch_sentence(self, sentence_id):
        if not self._article_cache:
            self._article_cache = self._fetch_article()
        sentence = self._article_cache.get(sentence_id)
        if not sentence:
            raise ValueError(f'Unknown sentence id for provided article: {sentence_id}')
        return sentence
    
    def clear(self):
        self._buffers = defaultdict(list)
        self._taxon_cache = None
        self._article_cache = None