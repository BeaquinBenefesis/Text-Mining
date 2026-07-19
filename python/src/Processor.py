from hitsUtils import HitsProcessor
from hitsUtils import HitType
from collections import deque
from sentence_utils import SentenceReader
from NormUtils import MirNormalizer, DefaultNormalizer, EntityNormalizer
from ArticleUtils import ArticleContext
from resources import MirResourceLoader
from typing import Iterable
from models import NormalizedHit
from collections import Counter
from dataclasses import dataclass, field

class Processor:
    
    def __init__(self,
                 hits_processor: HitsProcessor,
                 normalizers: dict[HitType, EntityNormalizer]):
        
        self.hits_processor = hits_processor       
        self.normalizers = normalizers
        self.processor_history = ProcessorHistory()
   
    def get_normalized_hit_stream(self, 
                                  sort_hits=True, 
                                  resolve_ambiguous_hits=True,
                                  print_summary: bool = True) -> Iterable['NormalizedHit']:
        article_context = ArticleContext()
        article_hits = deque()
        prev_article = None
        for hit in self.hits_processor.get_hits(sort=sort_hits, 
                                                 resolve_ambiguous=resolve_ambiguous_hits,
                                                 print_summary=print_summary) :
            self.processor_history.record_input_hit(hit)
            if prev_article and prev_article != hit.article_id:
                self.processor_history.record_article()
                yield from self._normalize_article(article_hits, article_context)
                article_context.clear()
                article_hits.clear()
            prev_article = hit.article_id
            article_context.add_hit(hit)
            article_hits.append(hit)
        if article_hits:
            self.processor_history.record_article()
            yield from self._normalize_article(article_hits, article_context)
        if print_summary:
            self.processor_history.print_summary()

    def _normalize_article(self, hits: Iterable['NormalizedHit'], context: ArticleContext):
        for raw_hit in hits:
            normalizer = self.normalizers[raw_hit.entity_type]
            for normalized_hit in normalizer.normalize(raw_hit, context):
                self.processor_history.record_output_hit(normalized_hit)
                yield normalized_hit

@dataclass
class ProcessorHistory: 
    input_hits: int = 0
    output_hits: int = 0
    articles_processed: int = 0
    dead_hits: int = 0
    entity_types: Counter = field(default_factory=Counter)
    normalization_statuses: Counter = field(default_factory=Counter)
    target_types: Counter = field(default_factory=Counter)
    
    def record_input_hit(self, hit: NormalizedHit):
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
