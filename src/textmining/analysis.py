import logging
from typing import Iterator, Optional
from itertools import groupby, combinations
from textmining.models import CandidateHit, NormalizedHit, HitType, Association, CoOccurence
from textmining.normalization import normalized_successfully

logger = logging.getLogger(__name__)


ENTITIES_PER_SENTENCE_CAP = 20

class ArticleStreamGuard:
    """Validates the ordering contract the downstream analysis relies on, and stamps
    each article with a monotone epoch.

    Since the external sort was dropped, articles arrive in the order syngrep emitted
    them (per-chunk blocks) rather than globally sorted, so ordering can no longer be
    checked by comparing article ids. Two properties still have to hold:

    1. Article contiguity -- all hits of an article arrive consecutively. Violating it
       makes AssociationEvidence open a second bucket for the same article and
       double-count its evidence. Detecting this genuinely needs a set of article ids;
       there is no O(1) test once global order is gone.
    2. Non-decreasing (section, sentence) *within* an article. Grouper.group_by_sentence
       uses itertools.groupby, which only collapses *adjacent* equal keys: a sentence
       split across two groups silently loses every co-occurrence between the halves.
       Any such split necessarily makes the key decrease, so this needs no set.

    One instance guards the whole stream, so the article-id map is paid once per run
    (~650k entries) rather than once per pipeline stage.
    """

    def __init__(self):
        self._epochs: dict[str, int] = {}
        self._article: Optional[str] = None
        self._sentence_key: tuple[int, int] = (-1, -1)

    def validate(self, hits: Iterator[NormalizedHit]) -> Iterator[NormalizedHit]:
        for hit in hits:
            if hit.article_id != self._article:
                if hit.article_id in self._epochs:
                    logger.critical('Article contiguity broken: %s reappears after %s',
                                    hit.article_id, self._article)
                    raise ValueError(f'Article contiguity broken: {hit.article_id} reappears')
                self._epochs[hit.article_id] = len(self._epochs)
                self._article = hit.article_id
                self._sentence_key = (hit.section_num, hit.sentence_num)
            else:
                sentence_key = (hit.section_num, hit.sentence_num)
                if sentence_key < self._sentence_key:
                    logger.critical('Sentences out of order in %s: %s after %s',
                                    hit.article_id, sentence_key, self._sentence_key)
                    raise ValueError(
                        f'Sentences out of order in {hit.article_id}: '
                        f'{sentence_key} after {self._sentence_key}'
                    )
                self._sentence_key = sentence_key
            yield hit

    def epoch(self, article_id: str) -> int:
        """Looked up by id rather than read off a 'current' counter: groupby reads one
        hit past the end of a group, so the counter may already have advanced."""
        return self._epochs[article_id]


def overlapping_pair(hit_a: CandidateHit, hit_b: CandidateHit) -> bool:
    if hit_a.sentence_id != hit_b.sentence_id:
        return False
    end_a = hit_a.start_position + hit_a.hit_length
    end_b = hit_b.start_position + hit_b.hit_length
    return hit_a.start_position < end_b and hit_b.start_position < end_a

def contained_pair(hit_a: CandidateHit, hit_b: CandidateHit) -> bool:
    '''Check if hit_a is contained in hit_b'''
    if hit_a.sentence_id != hit_b.sentence_id:
        return False
    end_a = hit_a.start_position + hit_a.hit_length
    end_b = hit_b.start_position + hit_b.hit_length
    return hit_b.start_position <= hit_a.start_position and end_b >= end_a


class Grouper:
    
    @staticmethod
    def group_by_sentence(hits: Iterator[CandidateHit]) -> Iterator[tuple[str, list[NormalizedHit]]]:
        for sentence_id, group in groupby(hits, key=lambda h: h.sentence_id):
            yield sentence_id, list(group)

    
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
            if overlapping_pair(hit_a, hit_b):
                continue
            yield (hit_a, hit_b) if hit_a.entity_type == HitType.MIR else (hit_b, hit_a)
    
    @staticmethod
    def extract_cooccurrences(hits: Iterator[NormalizedHit]) -> Iterator[CoOccurence]:
        guard = ArticleStreamGuard()
        for sentence_id, sentence_hits in Grouper.group_by_sentence(guard.validate(hits)):
            if len(sentence_hits) < 2:
                continue
            # Count distinct (start, length) spans, not raw hit rows: one literal
            # mention can produce several NormalizedHits (e.g. a species-ambiguous
            # miRNA mention resolves to one row per surviving taxon prefix), which
            # would otherwise inflate this count without adding real distinct
            # mentions.
            distinct_spans = {(h.start_position, h.hit_length) for h in sentence_hits}
            if len(distinct_spans) > ENTITIES_PER_SENTENCE_CAP:
                continue
            article_epoch = guard.epoch(sentence_hits[0].article_id)
            yield from (CoOccurence(article_id=hit_a.article_id,
                                    sentence_id=sentence_id,
                                    section_num=hit_a.section_num,
                                    origin_file_name=hit_a.origin_file_name,
                                    article_epoch=article_epoch,
                                    entity_types=(hit_a.entity_type, hit_b.entity_type),
                                    normalized_ids=(hit_a.normalization.normalized_id, hit_b.normalization.normalized_id),
                                    entity_positions=((hit_a.start_position, hit_a.start_position+hit_a.hit_length),
                                                      (hit_b.start_position, hit_b.start_position+hit_b.hit_length))) 
                        for hit_a, hit_b in Grouper.extract_valid_combinations(sentence_hits))

class EvidenceAggregator:
    
    def __init__(self):
        self.associations: dict[tuple[str, str], Association] = {}
    def record_coccurrence(self, cooc: CoOccurence) -> None:
        assoc = self.associations.setdefault(
            cooc.normalized_ids,
            Association(normalized_ids=cooc.normalized_ids,
                        entity_types=cooc.entity_types,)
        )
        assoc.record_cooccurrence(cooc)
