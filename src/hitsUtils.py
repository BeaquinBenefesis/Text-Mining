from src.SynFileUtils import MultiSynFileReader
import subprocess
import os
import tempfile
from collections import deque
import json
import glob
from itertools import zip_longest
from typing import Iterator, Optional
from collections import Counter
from src.models import HitType, SynonymType, HitGroup, GroupStatus, CandidateHit
from src.ArticleUtils import ArticleRecord, ArticleEvidence, ArticleMetadata, ArticleSource
from dataclasses import dataclass, field
from src.sentence_utils import parse_sentence_id
from src.Ontology import OntologyGraph

_SYNGREP_COL_NAMES = ["sentence_id","synonym_id","matched_text","start_position", "hit_length","synonym","prefix","suffix"]
_GOLD_COL_NAMES = ["sentence_id", "entity_id", "matched_text", "start_position", "hit_length", "entity_type", "mention_type"]

class HitsProcessor:

    def __init__(self, 
                 hits_path: str, 
                 synfile_map: str,
                 synfile_type_map: str,
                 type_to_ontology: dict[HitType, OntologyGraph], 
                 low_memory=False):
        
        self.hits_path = hits_path
        self.low_memory = low_memory
        self.type_map = HitsProcessor.parse_synfile_type_map(synfile_type_map)
        self.synfile_map = HitsProcessor.parse_synfile_map(synfile_map)
        self.synonym_paths = self.synfile_map.values()
        self.file_id_to_type = {
            syn_id: self.type_map[os.path.basename(path)]
            for syn_id, path in self.synfile_map.items()
        }
        self.type_to_ontology = type_to_ontology
        self.history = HitsProcessorHistory()
    
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

            hits_iter = self._iter_syngrep_hits(hits_path=hits_path, 
                                                remove_sent_id_prefix=remove_sent_id_prefix) if source == ArticleSource.SYSTEM else self._iter_gold_hits(hits_path)
            articles_iter = self._iter_articles(hits_iter, source)
            
            yield from articles_iter

            if print_summary:
                self.history.print_summary()

        finally:
            if sorted_path and os.path.exists(sorted_path):
                os.remove(sorted_path)
    
    def _iter_articles(self, hits: Iterator[CandidateHit], source) -> Iterator[ArticleRecord]:
        prev_hit = None
        prev_article = None
        hit_buffer = []
        for hit in hits:
            self.history.record_input_hit(hit)
            if prev_hit and not prev_hit.sort_key <= hit.sort_key:
                raise ValueError(f"Hits are not sorted. Can not resolve ambiguous hits! "
                                f"Previous hit: { prev_hit.sort_key}, current hit: {hit.sort_key}")
            current_article = hit.article_id
            if prev_article and current_article != prev_article:
                yield self.create_article(hit_buffer, source)
                hit_buffer.clear()
            hit_buffer.append(hit)
            prev_article = current_article
            prev_hit = hit
        if hit_buffer:
            yield self.create_article(hit_buffer, source)
    
    def create_article(self, article_hits: list[CandidateHit], source) -> ArticleRecord:
        if not article_hits:
            raise ValueError('Empty hit buffer passed to create ArticleRecord')
        self.history.record_article()
        if source == ArticleSource.SYSTEM:
            hit_groups = HitsProcessor._group_hits_by_span(article_hits)
            article_metadata = ArticleMetadata(article_id=article_hits[0].article_id)
            article_evidence = HitsProcessor._collect_article_evidence(hit_groups=hit_groups)
            resolved_hits = self._resolve_groups(hit_groups=hit_groups, article_evidence=article_evidence)
            return ArticleRecord(metadata=article_metadata, 
                                hits=article_hits, 
                                groups=hit_groups,
                                evidence=article_evidence, 
                                resolved_hits=resolved_hits)
        elif source == ArticleSource.GOLD:
            hit_groups = HitsProcessor._group_hits_by_span(article_hits)
            return ArticleRecord(metadata=ArticleMetadata(article_id=article_hits[0].article_id),
                                hits=article_hits,
                                groups=hit_groups,
                                evidence=ArticleEvidence(),
                                resolved_hits=article_hits)
        else:
            raise ValueError(f'Uknown article source: {source}')
            
    def _resolve_groups(self, hit_groups: list[HitGroup], article_evidence: ArticleEvidence) -> list[CandidateHit]:
        resolved_hits = []
        for g in hit_groups:
            if not g.is_ambiguous() and not g.contains_any_abbreviation():
                g.group_status = GroupStatus.EXACT_MATCH
                resolved_hits.append(g.get_first())
                continue
            filtered_hits = None
            if g.contains_inferred_abbreviation():
                # From abbreviation candidates (inferred and non-inferred ones), keep only the inferred abbreviations
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
            supported_ids = implied_ids & article_evidence.unambiguous_entity_ids
            if len(supported_ids) == 1:
                resolved_id = next(iter(supported_ids))
                hit = next(h for h in filtered_hits if h.entity_id == resolved_id)
                resolved_hits.append(hit)
                g.group_status = GroupStatus.RESOLVED
            elif len(supported_ids) > 1:
                entity_type_set = g.entity_type_set()
                if len(entity_type_set) != 1:
                   g.group_status = GroupStatus.AMBIGUOUS
                   continue
                entity_type = next(iter(entity_type_set))
                ontology = self.type_to_ontology.get(entity_type, None)
                if not ontology:
                    g.group_status = GroupStatus.AMBIGUOUS
                    continue
                lca = ontology.find_lca(*supported_ids)
                if not lca:
                    g.group_status = GroupStatus.AMBIGUOUS
                    continue
                else:
                    template = next(h for h in filtered_hits if h.entity_id in supported_ids)
                    inferred_hit = template.copy(entity_id=lca)
                    resolved_hits.append(inferred_hit)
                    g.group_status = GroupStatus.RESOLVED
            else:
                g.group_status = GroupStatus.FAILURE
        
        # RECORDING
        for g in hit_groups:
            self.history.record_group(g)
        for r in resolved_hits:
            self.history.record_output_hit(r)
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
                line_number = int(line_number)
                is_inferred_abbrev = len(synonym_parts) == 3

                if file_id not in self.synfile_map:
                    raise KeyError(f"No synonym file mapped for key: {file_id!r}")

                hit_type, is_abbrev = self.file_id_to_type[file_id]

                if is_inferred_abbrev and is_abbrev:
                    print(self.file_id_to_type)
                    raise RuntimeError(f'Found hit that is an abbreviation and an inferred abbreviation!\n{line}')
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
                    start_position=int(parts['start_position']),
                    hit_length=int(parts['hit_length']),
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
                    start_position=int(parts['start_position']),
                    hit_length=int(parts['hit_length']),
                    mention_type=parts['mention_type']                
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
                        is_abbrev_bool = is_abbrev.strip().lower() == 'true'
                        result_map[base_name] = (HitType(synfile_type), is_abbrev_bool)
                else:
                    raise ValueError(f'Synonym file(s) {synfile_path} could not be found!')
        return result_map


@dataclass
class HitsProcessorHistory:
    """Tracks stats across the raw-hit -> group -> resolved-hit pipeline in HitsProcessor."""

    input_hits: int = 0
    output_hits: int = 0
    articles_processed: int = 0

    input_entity_type_counts: Counter = field(default_factory=Counter)
    input_synonym_type_counts: Counter = field(default_factory=Counter)

    total_groups: int = 0
    multi_candidate_groups: int = 0          # groups that entered the disambiguation branch (ambiguous OR contains an abbreviation)
    multi_candidate_resolved: int = 0        # of those, how many ended up RESOLVED
    group_size_counts: Counter = field(default_factory=Counter)   # {group size: number of groups}
    group_status_counts: Counter = field(default_factory=Counter) # {GroupStatus: count}

    ambiguous_synonym_counts: Counter = field(default_factory=Counter)   # synonym -> times it produced an ambiguous group
    resolved_synonym_counts: Counter = field(default_factory=Counter)    # synonym -> times it resolved successfully
    unresolved_synonym_counts: Counter = field(default_factory=Counter)  # synonym -> times it stayed ambiguous/failed


    def record_input_hit(self, hit: CandidateHit) -> None:
        self.input_hits += 1
        self.input_entity_type_counts[hit.entity_type] += 1
        self.input_synonym_type_counts[hit.synonym_type] += 1

    def record_group(self, group: HitGroup) -> None:
        self.total_groups += 1
        group_size = len(group.hits)
        self.group_size_counts[group_size] += 1
        self.group_status_counts[group.group_status] += 1

        needs_disambiguation = group.is_ambiguous() or group.contains_any_abbreviation()
        if needs_disambiguation:
            self.multi_candidate_groups += 1
            if group.group_status == GroupStatus.RESOLVED:
                self.multi_candidate_resolved += 1

        synonym_key = self._synonym_key(group)
        if synonym_key is None:
            return

        if group.is_ambiguous():
            self.ambiguous_synonym_counts[synonym_key] += 1

        if group.group_status in (GroupStatus.EXACT_MATCH, GroupStatus.RESOLVED):
            self.resolved_synonym_counts[synonym_key] += 1
        elif group.group_status in (GroupStatus.AMBIGUOUS, GroupStatus.FAILURE):
            self.unresolved_synonym_counts[synonym_key] += 1

    def record_output_hit(self, hit: CandidateHit) -> None:
        self.output_hits += 1

    def record_article(self) -> None:
        self.articles_processed += 1

    @staticmethod
    def _synonym_key(group: HitGroup) -> Optional[str]:
        representative = group.get_first()
        if representative is None:
            return None
        # Prefer the dictionary synonym text; fall back to the raw matched text
        return representative.synonym or representative.raw_text

    @property
    def hits_collapsed(self) -> int:
        """How many raw hits were merged away by span-grouping (input - output)."""
        return self.input_hits - self.output_hits

    @property
    def resolution_rate(self) -> float:
        """Fraction of ALL groups that ended up resolved (EXACT_MATCH or RESOLVED)."""
        if self.total_groups == 0:
            return 0.0
        resolved = self.group_status_counts[GroupStatus.EXACT_MATCH] + self.group_status_counts[GroupStatus.RESOLVED]
        return resolved / self.total_groups

    @property
    def multi_candidate_resolution_rate(self) -> float:
        """Fraction of groups that needed disambiguation (ambiguous or contained an
        abbreviation) that ended up RESOLVED, as opposed to AMBIGUOUS/FAILURE."""
        if self.multi_candidate_groups == 0:
            return 0.0
        return self.multi_candidate_resolved / self.multi_candidate_groups


    def top_ambiguous_synonyms(self, n: int = 10):
        return self.ambiguous_synonym_counts.most_common(n)

    def top_resolved_synonyms(self, n: int = 10):
        return self.resolved_synonym_counts.most_common(n)

    def top_unresolved_synonyms(self, n: int = 10):
        return self.unresolved_synonym_counts.most_common(n)

    def print_summary(self, top_n: int = 10) -> None:
        print(f"{'--- HitsProcessor Summary ---':^40}")
        print(f"Articles Processed:      {self.articles_processed}")
        print(f"Input Hits:              {self.input_hits}")
        print(f"Output Hits:             {self.output_hits}")
        print(f"Hits Collapsed:          {self.hits_collapsed}")
        print(f"Total Groups:            {self.total_groups}")
        print(f"Multi-Candidate Groups:  {self.multi_candidate_groups}")
        print(f"Resolution Rate:         {self.resolution_rate:.2%}")
        print(f"Multi-Candidate Res. Rate: {self.multi_candidate_resolution_rate:.2%}")

        print("\nGroup Size Distribution:")
        for size, count in sorted(self.group_size_counts.items()):
            print(f"  size={size:<3}: {count}")

        print("\nInput Hits by Entity Type:")
        for entity, count in self.input_entity_type_counts.items():
            print(f"  {entity:<20}: {count}")

        print("\nInput Hits by Synonym Type:")
        for syn_type, count in self.input_synonym_type_counts.items():
            print(f"  {syn_type:<20}: {count}")

        print("\nGroups by Resolution Status:")
        for status, count in self.group_status_counts.items():
            print(f"  {status:<20}: {count}")

        print(f"\nTop {top_n} Synonyms Flagged Ambiguous:")
        for synonym, count in self.top_ambiguous_synonyms(top_n):
            print(f"  {synonym!r:<30}: {count}")

        print(f"\nTop {top_n} Synonyms Successfully Resolved:")
        for synonym, count in self.top_resolved_synonyms(top_n):
            print(f"  {synonym!r:<30}: {count}")

        print(f"\nTop {top_n} Synonyms Remaining Unresolved:")
        for synonym, count in self.top_unresolved_synonyms(top_n):
            print(f"  {synonym!r:<30}: {count}")