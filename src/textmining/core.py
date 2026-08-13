from typing import Iterator
from collections import Counter
from dataclasses import dataclass, field
import logging
from textmining.scoring import HitScorer
from textmining.article_utils import ArticleSource, ArticleRecord
from textmining.normalization import EntityNormalizer
from textmining.models import NormalizedHit, CandidateHit, NormalizationContext
from textmining.types import HitType, NormalizationStatus
from textmining.hit_utils import HitProcessor

logger = logging.getLogger(__name__)

class Processor:
    def __init__(self,
                 hits_processor: HitProcessor,
                 normalizers: dict[HitType, EntityNormalizer],
                 scorer: HitScorer):
        
        self.hits_processor = hits_processor       
        self.normalizers = normalizers
        self.scorer = scorer
        self.core_history = ProcessorHistory()
        logger.info("Core processor initialized")
   
    def _normalize_article(self, article: ArticleRecord, normalization_context: NormalizationContext) -> list[NormalizedHit]:
        normalized_hits: NormalizedHit = []
        for candidate_hit in article.resolved_hits:
            self.core_history.record_input_hit(candidate_hit)
            normalizer = self.normalizers[candidate_hit.entity_type]
            normalized_hits.extend(normalizer.normalize(candidate_hit, normalization_context))
        for normalized_hit in normalized_hits:
            norm_status = normalized_hit.normalization.status
            if not normalized_hit.normalization.dead and (norm_status == NormalizationStatus.NORMALIZED 
                                                          or norm_status == NormalizationStatus.FALLBACK):
                normalized_hit.score = self.scorer.compute_score(normalized_hit.entity_type, normalized_hit.normalization.normalized_id)
                self.core_history.record_output_hit(normalized_hit)
        return normalized_hits
                 
    def get_normalized_article_stream(self,
                                      sort_hits=True,
                                      print_summary = True) -> Iterator[ArticleRecord]:
        for article in self.hits_processor.read_articles(source=ArticleSource.SYSTEM,
                                                         remove_sent_id_prefix=True,
                                                         sort=sort_hits,
                                                         print_summary=print_summary):
            context = Processor._build_normalization_context(article.resolved_hits)
            article.normalized_hits = self._normalize_article(article, context)
            self.core_history.record_article()
            yield article
            
    
    @staticmethod
    def _build_normalization_context(resolved_hits: list[CandidateHit]) -> NormalizationContext:
        context = NormalizationContext()
        for hit in resolved_hits:
            context.add_hit(hit)
        return context
            

@dataclass
class ProcessorHistory: 
    input_hits: int = 0
    output_hits: int = 0
    dead_hits: int = 0
    entity_types: Counter = field(default_factory=Counter)
    normalization_statuses: Counter = field(default_factory=Counter)
    target_types: Counter = field(default_factory=Counter)
    articles_processed: int = 0
    
    def record_input_hit(self, hit: CandidateHit):
        self.input_hits += 1
        self.entity_types[hit.entity_type] += 1
    
    def record_output_hit(self, hit: NormalizedHit):
        self.output_hits += 1
        self.entity_types[hit.entity_type] += 1
        if hit.normalization:
            self.normalization_statuses[hit.normalization.status] += 1
            if hit.normalization.target_type is not None:
                self.target_types[hit.normalization.target_type] += 1
            if hit.normalization.dead:
                self.dead_hits += 1
    
    def record_article(self):
        self.articles_processed += 1
        
    def print_summary(self):
        print(f"{'--- Processor Summary ---':^40}")
        print(f"Articles Processed: {self.articles_processed}")
        print(f"Input Hits:         {self.input_hits}")
        print(f"Output Hits:        {self.output_hits}")
        print(f"Dead Hits:          {self.dead_hits}")
        if self.input_hits:
            expansion_ratio = self.output_hits / self.input_hits
            print(f"Output/Input Ratio: {expansion_ratio:.2f}")
        print("\nBreakdown by Entity Type:")
        for entity, count in self.entity_types.items():
            print(f"  {entity:<20}: {count}")
        print("\nBreakdown by Normalization Status:")
        for status, count in self.normalization_statuses.items():
            print(f"  {status:<20}: {count}")
        print("\nBreakdown by Target Type:")
        for target, count in self.target_types.items():
            print(f"  {target:<20}: {count}")
