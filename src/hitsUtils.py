from .SynFileUtils import MultiSynFileReader
import subprocess
import os
import tempfile
from collections import deque
import json
import glob
from itertools import zip_longest
from typing import Iterator
from collections import Counter
from .models import HitType, SynonymType, HitGroup, GroupStatus, CandidateHit
from .ArticleUtils import ArticleRecord, ArticleEvidence, ArticleMetadata, ArticleSource
from dataclasses import dataclass, field
from .sentence_utils import parse_sentence_id

_SYNGREP_COL_NAMES = ["sentence_id","synonym_id","matched_text","start_position", "hit_length","synonym","prefix","suffix"]
_GOLD_COL_NAMES = ["sentence_id", "entity_id", "entity_type", "matched_text", "start_position", "hit_length"]

class HitsProcessor:

    def __init__(self, hits_path, synfile_map, synfile_type_map, low_memory=False):
        self.hits_path = hits_path
        self.low_memory = low_memory
        self.type_map = HitsProcessor.parse_synfile_type_map(synfile_type_map)
        self.synfile_map = HitsProcessor.parse_synfile_map(synfile_map)
        self.synonym_paths = self.synfile_map.values()
        self.file_id_to_type = {
            syn_id: self.type_map[os.path.basename(path)]
            for syn_id, path in self.synfile_map.items()
        }     
    
    def read_articles(self,
                    source:ArticleSource = ArticleSource.SYSTEM,
                    remove_sent_id_prefix=True, 
                    sort=False, 
                    print_summary=True,) -> Iterator[ArticleRecord]:
        
        sorted_path = None
        try:
            hits_path = self.hits_path
            if sort:
                sorted_fd, sorted_path = tempfile.mkstemp()
                os.close(sorted_fd)
                subprocess.run(
                    ['sort', '-t\t', '-k1,1V', '-k4,4n', self.hits_path, '-o', sorted_path],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                hits_path = sorted_path

            hits_iter = self._iter_hits(hits_path=hits_path, remove_sent_id_prefix=remove_sent_id_prefix)
            articles_iter = self._iter_articles(hits_iter, source)
            
            yield from articles_iter

            if print_summary:
                pass

        finally:
            if sorted_path and os.path.exists(sorted_path):
                os.remove(sorted_path)
        
    def _iter_articles(self, hits: Iterator[CandidateHit], source) -> Iterator[ArticleRecord]:
        prev_hit = None
        prev_article = None
        hit_buffer = []
        for hit in hits:
            if prev_hit and not prev_hit.sort_key <= hit.sort_key:
                raise ValueError(f"Hits are not sorted. Can not resolve ambiguous hits! "
                                f"Previous hit: {prev_hit.sentence_id}, current hit: {hit.sentence_id}")
            current_article = hit.article_id
            if prev_article and current_article != prev_article:
                yield HitsProcessor.create_article(hit_buffer, source)
                hit_buffer.clear()
            hit_buffer.append(hit)
            prev_article = current_article
            prev_hit = hit
        if hit_buffer:
            yield HitsProcessor.create_article(hit_buffer, source)
    
    @staticmethod
    def create_article(article_hits: list[CandidateHit], source) -> ArticleRecord:
        if not article_hits:
            raise ValueError('Empty hit buffer passed to create ArticleRecord')
        
        if source == ArticleSource.SYSTEM:
            hit_groups = HitsProcessor._group_hits_by_span(article_hits)
            article_metadata = ArticleMetadata(article_id=article_hits[0].article_id)
            article_evidence = HitsProcessor._collect_article_evidence(hit_groups=hit_groups)
            resolved_hits = HitsProcessor._resolve_groups(hit_groups=hit_groups, article_evidence=article_evidence)
            return ArticleRecord(metadata=article_metadata, 
                                hits=article_hits, 
                                groups=hit_groups,
                                evidence=article_evidence, 
                                resolved_hits=resolved_hits)
        elif source == ArticleSource.GOLD:
            hit_groups = HitsProcessor._group_hits_by_span(article_hits)
            return ArticleRecord(metadata=ArticleMetadata(article_id=article_hits[0].article_id),
                                source=source,
                                hits=article_hits,
                                groups=hit_groups,
                                evidence=ArticleEvidence(),
                                resolved_hits=article_hits)
        else:
            raise ValueError(f'Uknown article source: {source}')
            
    @staticmethod
    def _resolve_groups(hit_groups: list[HitGroup], article_evidence: ArticleEvidence):
        resolved_hits = []
        for g in hit_groups:
            if not g.is_ambiguous() and not g.contains_any_abbreviation():
                g.group_status = GroupStatus.EXACT_MATCH
                resolved_hits.extend(g.get_first())
                continue
            filtered_hits = None
            if g.contains_inferred_abbreviation():
                # Among abbreviation candidates, keep only the inferred abbreviations
                filtered_hits = [h for h in g.hits if h.synonym_type != SynonymType.ABBREVIATION]
            elif g.contains_abbreviation():
                filtered_hits = [h for h in g.hits if (h.synonym_type != SynonymType.ABBREVIATION) or (h.entity_id in article_evidence.unambiguous_entity_ids)]
            else:
                filtered_hits = g.hits
            if not filtered_hits:
                g.group_status = GroupStatus.FAILURE
                continue
            implied_ids = {h.entity_id for h in filtered_hits}
            if len(implied_ids) == 1:
                resolved_id = next(iter(implied_ids))
                hit = next(h for h in filtered_hits if h.entity_id == resolved_id)
                resolved_hits.append(hit)
                g.group_status = GroupStatus.RESOLVED
                continue
            intersection = implied_ids & article_evidence.unambiguous_entity_ids
            if len(intersection) == 1:
                resolved_id = next(iter(intersection))
                hit = next(h for h in filtered_hits if h.entity_id == resolved_id)
                resolved_hits.append(hit)
                g.group_status = GroupStatus.RESOLVED
            else:
                g.group_status = GroupStatus.AMBIGUOUS if len(intersection) > 1 else GroupStatus.FAILURE
        return resolved_hits
                    
    @staticmethod
    def _collect_article_evidence(hit_groups: list[HitGroup]) -> ArticleEvidence:
        unambiguous_entity_ids = {g.get_first().entity_id for g in hit_groups 
                            if not g.is_ambiguous() and g.get_first().synonym_type != SynonymType.ABBREVIATION}
        return ArticleEvidence(unambiguous_entity_ids=unambiguous_entity_ids)
        
    
    # Find hits mapping to exactly the same positions
    @staticmethod   
    def _group_hits_by_span(unprocessed_hits: list[CandidateHit]) -> list[HitGroup]:
        groups = []
        current_group = HitGroup()
        prev_span = None 
        for hit in unprocessed_hits:
            span = hit.sort_key
            if prev_span is not None and span != prev_span:
                groups.append(current_group)
                current_group = HitGroup()
            current_group.add_hit(hit)
            prev_span = span
        if current_group.hits:
            groups.append(current_group)
        return groups                                 
      
    def _iter_syngrep_hits(self, hits_path, remove_sent_id_prefix=True) -> Iterator[CandidateHit]:
        with MultiSynFileReader(self.low_memory) as reader, open(hits_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                parts = dict(zip_longest(_SYNGREP_COL_NAMES, line.split('\t'), fillvalue=''))

                synonym_id = parts['synonym_id']
                synonym_parts = synonym_id.split(':', 2)
                file_id, line_number = synonym_parts[:2]
                is_inferred_abbrev = len(synonym_parts) == 3

                if file_id not in self.synfile_map:
                    raise KeyError(f"No synonym file mapped for key: {file_id!r}")

                hit_type, is_abbrev = self.file_id_to_type[file_id]

                if is_inferred_abbrev and is_abbrev:
                    raise RuntimeError('Found hit that is an abbreviation and an inferred abbreviation!')
                elif is_inferred_abbrev:
                    synonym_type = SynonymType.INFERRED_ABBREVIATION
                elif is_abbrev:
                    synonym_type = SynonymType.ABBREVIATION
                else:
                    synonym_type = SynonymType.STANDARD

                sentence_id = parts['sentence_id']
                if remove_sent_id_prefix and ':' in sentence_id:
                    sentence_id = sentence_id.split(':', 1)[1]

                file_path = self.synfile_map[file_id]
                entity_id = reader.extract_id(file_path, line_number)

                yield CandidateHit(
                    entity_type=hit_type,
                    synonym_type=synonym_type,
                    sentence_id=sentence_id,
                    synonym_id=synonym_id,
                    entity_id=entity_id,
                    raw_text=parts['matched_text'],
                    start_position=parts['start_position'],
                    hit_length=parts['hit_length'],
                    synonym=parts['synonym'],
                    prefix=parts['prefix'],
                    suffix=parts['suffix'],
                )

    def _iter_gold_hits(self, hits_path):
        with open(hits_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = dict(zip(_GOLD_COL_NAMES, line.split('\t')))

                yield CandidateHit(
                    entity_type=parts['entity_type'],
                    synonym_type=SynonymType.STANDARD,
                    sentence_id=parts['sentence_id'],
                    entity_id=parts['entity_id'],
                    raw_text=parts['matched_text'],
                    start_position=parts['start_position'],
                    hit_length=parts['hit_length']                    
                )
    
    @staticmethod        
    def parse_synfile_map(path) -> dict:
        map = {}
        if not path:
            return map
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                synfile_path, synfile_id = line.split('\t')
                map[synfile_id] = synfile_path
        return map
    
    @staticmethod
    def parse_synfile_type_map(path):
        result_map = {}
        if not path:
            return map
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:  # Skip empty lines if any
                    continue
                    
                synfile_path, synfile_type, is_abbrev = line.split('\t')
                
                expanded_paths = glob.glob(synfile_path, recursive=True)
                
                if expanded_paths:
                    for matched_path in expanded_paths:
                        base_name = os.path.basename(matched_path)
                        if base_name in result_map:
                            raise ValueError(f'Conficting synonym file names: {base_name}')
                        result_map[base_name] = (HitType(synfile_type), bool(is_abbrev))
                else:
                    raise ValueError(f'Synonym file(s) {synfile_path} could not be found!')
        return result_map

from syngrep import run_syngrep

disease_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/disease.syn'
disease_abbrev_path = '/mnt/extstudtemp/mitsopoulos/Text-Mining/disease_abbreviations.txt'
sentences = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/validation/disease/NCBI_disease/processed_text/NCBItestset_corpus.sent'
synonyms = {HitType.DISEASE: [disease_path]}
abbrevs = {HitType.DISEASE: [disease_abbrev_path]}
output_dir = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/validation/disease/NCBI_disease/out_hits_test_1'
output_name = 'output'
model_hits = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/validation/disease/NCBI_disease/model_hits/NCBItestset_corpus.hits'
mapping = '/mnt/extstudtemp/mitsopoulos/Text-Mining/disease_mapping.json'

res = run_syngrep(sentence_pattern=sentences,
            synonyms=synonyms,
            abbrev_synonyms=abbrevs,
            output_dir=output_dir,
            output_name=output_name,
            abbrev=False)