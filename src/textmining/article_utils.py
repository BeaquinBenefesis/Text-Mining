from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from textmining.models import CandidateHit, NormalizedHit, HitGroup


@dataclass
class ArticleEvidence:
    unambiguous_entity_ids: Optional[set[str]] = field(default_factory=set)

@dataclass
class ArticleMetadata:
    article_id: str

@dataclass
class ArticleRecord:
    metadata: ArticleMetadata
    hits: list[CandidateHit] = field(default_factory=list)
    groups: list[HitGroup] = field(default_factory=list)
    evidence: ArticleEvidence = field(default_factory=ArticleEvidence)
    resolved_hits: list[CandidateHit] = field(default_factory=list)
    normalized_hits: list[NormalizedHit] = field(default_factory=list)


class ArticleSource(str, Enum):
    SYSTEM = 'SYSTEM'
    GOLD = 'GOLD'
