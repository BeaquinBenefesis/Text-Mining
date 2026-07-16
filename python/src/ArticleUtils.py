from collections import defaultdict
from collections import deque
from hitsUtils import HitType

class ArticleContext:
    def __init__(self):
        self._buffers = defaultdict(deque)
        self._taxon_cache = None
    
    def add_hit(self, hit):
        self._buffers[hit['type']].append(hit)
    
    def hits_of(self, hit_type):
        return self._buffers.get(hit_type, deque())
    
    def get_taxon_relevance(self):
        if self._taxon_cache:
            return self._taxon_cache
        tax_buffer = self._buffers[HitType.TAXON]
        relevance = {tax['synonym_id'] : 1 for tax in tax_buffer}
        self._taxon_cache = relevance
        return relevance
    
    def clear(self):
        self._buffers = defaultdict(deque)
        self._taxon_cache = None

