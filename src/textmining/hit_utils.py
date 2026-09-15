import subprocess
import os
import tempfile
import shutil
import glob
import logging
from typing import Iterator, Optional
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from textmining.enums import HitType, SynonymType, GroupStatus
from textmining.models import HitGroup, CandidateHit
from textmining.article_utils import ArticleRecord, ArticleEvidence, ArticleMetadata, ArticleSource
from textmining.ontology import OntologyGraph
from textmining.synonym_utils import MultiSynFileReader
from textmining.analysis import overlapping_pair, contained_pair
from textmining.normalization import MirNormalizer


#_SYNGREP_COL_NAMES = ["sentence_id","synonym_id","matched_text","start_position", "hit_length","synonym","prefix","suffix"]
#_GOLD_COL_NAMES = ["sentence_id", "entity_id", "matched_text", "start_position", "hit_length", "entity_type", "mention_type"]

logger = logging.getLogger(__name__)


class HitProcessor:

    def __init__(self,
                 hits_path: str,
                 synfile_map: str,
                 synfile_type_map: str,
                 type_to_ontology: dict[HitType, OntologyGraph],
                 low_memory=False,
                 mir_normalizer: Optional[MirNormalizer] = None):

        self.hits_path = hits_path
        self.low_memory = low_memory
        self.type_map = HitProcessor.parse_synfile_type_map(synfile_type_map)
        self.synfile_map = HitProcessor.parse_synfile_map(synfile_map)
        self.type_to_ontology = type_to_ontology
        self.mir_normalizer = mir_normalizer
        self.history = HitProcessorHistory()
        logger.info(
            "Initialized HitProcessor: hits_path=%s, %d synonym files, low_memory=%s",
            hits_path, len(self.synfile_map), low_memory,
        )
        logger.debug("synfile_map=%s", self.synfile_map)
        
    def read_articles(self,
                      source:ArticleSource = ArticleSource.SYSTEM,
                      print_summary=True,) -> Iterator[ArticleRecord]:
        
        hits_iter = (self._resolve_syngrep_hits_entity_ids(self._iter_syngrep_hits(hits_path=self.hits_path,
                                                synfile_map=self.synfile_map,
                                                synfile_type_map=self.type_map,
                                                low_memory=self.low_memory))
                    if source == ArticleSource.SYSTEM else self._iter_gold_hits(self.hits_path))
        articles_iter = self._iter_articles(hits_iter, source)
        
        yield from articles_iter

        if print_summary:
            self.history.print_summary()
            logger.info(
                'HitProcessor run complete: articles=%d, input_hits=%d, output_hits=%d, resolution_rate=%.2f%%',
                self.history.articles_processed, self.history.input_hits,
                self.history.output_hits, self.history.resolution_rate * 100,
            )
    
    def _iter_articles(self, hits: Iterator[CandidateHit], source) -> Iterator[ArticleRecord]:
        prev_article = None
        hit_buffer = []
        seen_articles = set()
        for hit in hits:
            self.history.record_input_hit(hit)
            current_article = hit.article_id
            if prev_article is not None and current_article != prev_article:
                if current_article in seen_articles:
                    logger.critical('Article contiguity broken: %s reappears after %s', current_article, prev_article)
                    raise ValueError(f'Invalid hits input. Article contiguity broken: {current_article} reappears!')
                # Record the article being *closed*, not the one being opened: the
                # open one is still current and must not count as already seen.
                seen_articles.add(prev_article)
                yield self.create_article(hit_buffer, source)
                hit_buffer = []
            hit_buffer.append(hit)
            prev_article = current_article
        if hit_buffer:
            yield self.create_article(hit_buffer, source)
    
    def create_article(self, article_hits: list[CandidateHit], source) -> ArticleRecord:
        if not article_hits:
            logger.critical('Empty hit buffer passed to create ArticleRecord')
            raise ValueError('Empty hit buffer passed to create ArticleRecord')
        self.history.record_article()
        article_hits.sort(key=lambda h: h.sort_key)
        if source == ArticleSource.SYSTEM:
            hit_groups = HitProcessor._group_hits_by_span(article_hits)
            hit_groups = HitProcessor._drop_contained_groups(hit_groups)
            article_metadata = ArticleMetadata(article_id=article_hits[0].article_id)
            article_evidence = HitProcessor._collect_article_evidence(hit_groups=hit_groups)
            resolved_hits = self._resolve_groups(hit_groups=hit_groups, article_evidence=article_evidence)
            return ArticleRecord(metadata=article_metadata, 
                                hits=article_hits, 
                                groups=hit_groups,
                                evidence=article_evidence, 
                                resolved_hits=resolved_hits)
        elif source == ArticleSource.GOLD:
            hit_groups = HitProcessor._group_hits_by_span(article_hits)
            return ArticleRecord(metadata=ArticleMetadata(article_id=article_hits[0].article_id),
                                hits=article_hits,
                                groups=hit_groups,
                                evidence=ArticleEvidence(),
                                resolved_hits=article_hits)
        else:
            raise ValueError(f'Uknown article source: {source}')
            
    # A group can hold candidates of different entity_types at the same span
    # (e.g. "bantam" the miRNA vs. "bantam" the chicken gene). If one of them is a
    # MIR hit with a well-formed prefix/suffix, prefer it over same-span
    # candidates of other types
    def _prefer_contextual_mir(self, hits: list[CandidateHit]) -> list[CandidateHit]:
        if not self.mir_normalizer:
            return hits
        entity_types = {h.entity_type for h in hits}
        if len(entity_types) <= 1 or HitType.MIR not in entity_types:
            return hits
        contextual_mir_hits = [
            h for h in hits
            if h.entity_type == HitType.MIR and self.mir_normalizer.has_mirna_shaped_context(h.prefix, h.suffix)
        ]
        if not contextual_mir_hits:
            return hits
        logger.debug(
            "Preferring contextual MIR hit(s) over %d same-span non-MIR candidate(s) at %s",
            len(hits) - len(contextual_mir_hits), hits[0].sort_key,
        )
        return contextual_mir_hits

    def _resolve_groups(self, hit_groups: list[HitGroup], article_evidence: ArticleEvidence) -> list[CandidateHit]:
        resolved_hits = []
        group_starts = []   # index into resolved_hits where each group's output begins
        for g in hit_groups:
            group_starts.append(len(resolved_hits))
            if not g.is_ambiguous() and not g.contains_any_abbreviation():
                g.group_status = GroupStatus.EXACT_MATCH
                resolved_hits.append(g.get_first())
                continue
            
            logger.debug(
                "Disambiguating group at %s: %d hits, ambiguous=%s, has_abbrev=%s",
                g.get_first().sort_key if g.get_first() else None,
                len(g.hits), g.is_ambiguous(), g.contains_any_abbreviation(),
            )
            
            filtered_hits = None
            if g.contains_inferred_abbreviation():
                # An in-text definition exists: drop dictionary abbreviations of every type.
                # Standard and inferred hits of every type are kept.
                filtered_hits = [h for h in g.hits if h.synonym_type != SynonymType.ABBREVIATION]
            elif g.contains_abbreviation():
                filtered_hits = [h for h in g.hits 
                                 if (h.synonym_type != SynonymType.ABBREVIATION) 
                                 or (h.entity_id in article_evidence.unambiguous_entity_ids)]
            else:
                filtered_hits = g.hits

            filtered_hits = self._prefer_contextual_mir(filtered_hits)

            if not filtered_hits:
                g.group_status = GroupStatus.FAILURE
                logger.debug("Group resolution FAILED: no candidates left after filtering")
                continue
            
            implied_ids = {h.entity_id for h in filtered_hits}
           
            if len(implied_ids) == 1:
                resolved_id = next(iter(implied_ids))
                hit = next(h for h in filtered_hits if h.entity_id == resolved_id)
                resolved_hits.append(hit)
                g.group_status = GroupStatus.RESOLVED
                continue

            entity_type_set = {h.entity_type for h in filtered_hits}
            if HitType.MIR in entity_type_set:
                supported = {h.entity_id for h in filtered_hits} & article_evidence.unambiguous_entity_ids
                if len(supported) == 1:
                    hit = next(h for h in filtered_hits if h.entity_id in supported)
                    resolved_hits.append(hit)
                    g.group_status = GroupStatus.RESOLVED
                else:
                    logger.debug("Group AMBIGUOUS_ENTITY_TYPE: MIR collision without a single supported id, types=%s, supported=%s",
                                 entity_type_set, supported)
                    g.group_status = GroupStatus.AMBIGUOUS_ENTITY_TYPE
                continue
            
            hits_by_type = defaultdict(list)
            for h in filtered_hits:
                hits_by_type[h.entity_type].append(h)
            
            
            statuses = set()
            accepted_types = []
            for hits in hits_by_type.values():
                hit, status = self._resolve_single_type(hits, article_evidence)
                if hit is not None:
                    resolved_hits.append(hit)
                    accepted_types.append(hit.entity_type)
                statuses.add(status)
            
            if len(statuses) == 1:
                group_status = next(iter(statuses))
                if group_status == GroupStatus.RESOLVED:
                    if len(hits_by_type.keys()) == 1:
                        g.group_status = GroupStatus.RESOLVED
                    else:
                        g.group_status = GroupStatus.RESOLVED_MULTI_TYPE
                else:
                    g.group_status = GroupStatus.AMBIGUOUS_ID
            else:
                g.group_status = GroupStatus.PARTIALLY_RESOLVED
            logger.debug("Split group at %s: %d/%d type(s) accepted %s, ids per type %s -> %s",
                         g.get_first().sort_key, len(accepted_types), len(hits_by_type),
                         [t.name for t in accepted_types],
                         {t.name: sorted({h.entity_id for h in hs}) for t, hs in hits_by_type.items()},
                         g.group_status)
            
    
        # RECORDING
        group_ends = group_starts[1:] + [len(resolved_hits)]
        for g, start, end in zip(hit_groups, group_starts, group_ends):
            self.history.record_group(g, emitted_hits=end - start)
        for r in resolved_hits:
            self.history.record_output_hit(r)
        return resolved_hits
    
    def _resolve_single_type(self, hits: list[CandidateHit], evidence: ArticleEvidence) -> tuple[Optional[CandidateHit], GroupStatus]:
        ids = {h.entity_id for h in hits}
        
        if len(ids) == 1:
            return next(h for h in hits if h.entity_id in ids), GroupStatus.RESOLVED
        
        supported = ids & evidence.unambiguous_entity_ids
        
        if len(supported) == 1:
            return next(h for h in hits if h.entity_id in supported), GroupStatus.RESOLVED
        
        entity_type = hits[0].entity_type
        ontology = self.type_to_ontology.get(entity_type, None)
        
        if not ontology:
            logger.warning("No ontology configured for entity_type=%s; leaving part AMBIGUOUS_ID", entity_type)
            return None, GroupStatus.AMBIGUOUS_ID
        
        lca = ontology.find_lca(*ids)
        if lca is None:
            logger.debug("No LCA found for ids=%s (type=%s)", ids, entity_type)
            return None, GroupStatus.AMBIGUOUS_ID
        
        template = hits[0]
        inferred_hit = template.copy(entity_id=lca)
        logger.debug("Resolved part via LCA: ids=%s -> lca=%s (type=%s)", ids, lca, entity_type)
        return inferred_hit, GroupStatus.RESOLVED
        
            
        
                    
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
    
    
    @staticmethod
    def _drop_contained_groups(groups: list[HitGroup]):
        groups_out = []
        envelope = None

        for group in groups:
            cand = group.get_first()
            if envelope is None:
                envelope = group
                continue

            env_cand = envelope.get_first()
            if contained_pair(cand, env_cand):
                logger.debug(
                    "Dropping contained hit %s (%r, span %d:%d) inside %s (%r, span %d:%d)",
                    cand.synonym_id, cand.raw_text, cand.start_position, cand.start_position + cand.hit_length,
                    env_cand.synonym_id, env_cand.raw_text, env_cand.start_position, env_cand.start_position + env_cand.hit_length,
                )
                continue
            elif contained_pair(env_cand, cand):
                logger.debug(
                    "Dropping contained hit %s (%r, span %d:%d) inside %s (%r, span %d:%d)",
                    env_cand.synonym_id, env_cand.raw_text, env_cand.start_position, env_cand.start_position + env_cand.hit_length,
                    cand.synonym_id, cand.raw_text, cand.start_position, cand.start_position + cand.hit_length,
                )
                envelope = group
            else:
                if overlapping_pair(cand, env_cand):
                    logger.warning(
                        "Partial (non-containing) span overlap: %s (%r, span %d:%d) vs %s (%r, span %d:%d) in sentence: %s",
                        env_cand.synonym_id, env_cand.raw_text, env_cand.start_position, env_cand.start_position + env_cand.hit_length,
                        cand.synonym_id, cand.raw_text, cand.start_position, cand.start_position + cand.hit_length, cand.sentence_id,
                    )
                groups_out.append(envelope)
                envelope = group

        if envelope:
            groups_out.append(envelope)

        return groups_out
            
    
    def _resolve_syngrep_hits_entity_ids(self, hit_stream: Iterator[CandidateHit]) -> Iterator[CandidateHit]:
        entity_id = None
        for hit in hit_stream:
            if hit.entity_type == HitType.MIR:
                yield hit
            else:
                entity_id = self.type_to_ontology[hit.entity_type].resolve_id(hit.entity_id)
                if not entity_id:
                    logger.error('Could not resolve id: %s', hit.entity_id)
                    continue
                else:
                    hit.entity_id = entity_id
                    yield hit
    
    @staticmethod
    def _iter_syngrep_hits(hits_path: str | Path,
                           synfile_map: dict[str, str],
                           synfile_type_map: dict[str, tuple[HitType, bool]],
                           low_memory=False) -> Iterator[CandidateHit]:
        with MultiSynFileReader(low_memory) as reader, open(hits_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                parts = line.split('\t')
                parts += [''] * (8 - len(parts))
                
                if len(parts) != 8:
                    logger.critical('Illegal hit format! %s', line)
                    raise ValueError(f'Illegal hit format!: {parts}')
                
                sentence_id, synonym_id, matched_text, start, length, synonym, prefix, suffix = parts

                synonym_parts = synonym_id.split(':', 2)
                if len(synonym_parts) < 2:
                    logger.error("Dubious synonym format: %s", line)
                    continue
                file_id, line_number = synonym_parts[:2]
                line_number = int(line_number)
                is_inferred_abbrev = len(synonym_parts) == 3

                if file_id not in synfile_map:
                    logger.warning("No synonym file mapped for key: %s", file_id)
                    raise KeyError(f"No synonym file mapped for key: {file_id!r}")

                file_path = synfile_map[file_id]
                hit_type, is_abbrev = synfile_type_map[file_path.name]
        
                if is_inferred_abbrev and is_abbrev:
                    logger.warning("Found hit that is an abbreviation and an inferred abbreviation!")
                    #TODO: For now just skip, change later
                    continue
                elif is_inferred_abbrev:
                    synonym_type = SynonymType.INFERRED_ABBREVIATION
                elif is_abbrev:
                    synonym_type = SynonymType.ABBREVIATION
                else:
                    synonym_type = SynonymType.STANDARD

                if ':' not in sentence_id:
                    raise ValueError(f'Dubious sentence_id format. Expected article_souce:sent_id, got {sentence_id}')
                article_source, sentence_id = sentence_id.split(':', 1)

                raw_entity_id = reader.extract_id(str(file_path), line_number)

                yield CandidateHit(
                    entity_type=hit_type,
                    synonym_type=synonym_type,
                    sentence_id=sentence_id,
                    synonym_id=synonym_id,
                    entity_id=raw_entity_id,
                    raw_text=matched_text,
                    start_position=int(start),
                    hit_length=int(length),
                    synonym=synonym,
                    prefix=prefix,
                    suffix=suffix,
                    origin_file_name=article_source,
                )

    def _iter_gold_hits(self, hits_path):
        with open(hits_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                parts = line.split('\t')
                sentence_id, entity_id, matched_text, start, length, entity_type, mention_type = parts

                yield CandidateHit(
                    entity_type=HitType(entity_type),
                    synonym_type=SynonymType.STANDARD,
                    sentence_id=sentence_id,
                    entity_id=entity_id,
                    raw_text=matched_text,
                    start_position=int(start),
                    hit_length=int(length),
                    mention_type=mention_type                
                )
    
    @staticmethod        
    def parse_synfile_map(path: str | Path) -> dict[str, Path]:
        synfile_map = {}
        if not path:
            return synfile_map
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                synfile_path, synfile_id = line.split('\t')
                synfile_path = Path(synfile_path)
                if not synfile_path.exists():
                    raise FileNotFoundError(f"Synonym file: {synfile_path} does not exist.")
                synfile_map[synfile_id] = synfile_path
        return synfile_map
    
    @staticmethod
    def parse_synfile_type_map(path: str | Path) -> dict[str, tuple[HitType, bool]]:
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


# Statuses under which a group emitted at least one hit
RESOLVED_STATUSES = (
    GroupStatus.EXACT_MATCH,
    GroupStatus.RESOLVED,
    GroupStatus.RESOLVED_MULTI_TYPE,
    GroupStatus.PARTIALLY_RESOLVED,
)


@dataclass
class HitProcessorHistory:
    """Tracks stats across the raw-hit -> group -> resolved-hit pipeline in HitProcessor."""

    input_hits: int = 0
    output_hits: int = 0
    articles_processed: int = 0

    input_entity_type_counts: Counter = field(default_factory=Counter)
    input_synonym_type_counts: Counter = field(default_factory=Counter)

    total_groups: int = 0
    multi_candidate_groups: int = 0          # groups that entered the disambiguation branch (ambiguous OR contains an abbreviation)
    multi_candidate_resolved: int = 0        # of those, how many ended up resolved (see RESOLVED_STATUSES)
    group_size_counts: Counter = field(default_factory=Counter)   # {group size: number of groups}
    group_status_counts: Counter = field(default_factory=Counter) # {GroupStatus: count}
    # {hits emitted by one group: number of groups}; > 1 only for split multi-type groups
    emitted_hits_per_group_counts: Counter = field(default_factory=Counter)

    ambiguous_synonym_counts: Counter = field(default_factory=Counter)   # synonym -> times it produced an ambiguous group
    resolved_synonym_counts: Counter = field(default_factory=Counter)    # synonym -> times it resolved successfully
    # synonym -> times its group was split and only some type parts resolved (also counted as resolved)
    partially_resolved_synonym_counts: Counter = field(default_factory=Counter)
    # synonym -> times it stayed unresolved, broken out per GroupStatus (AMBIGUOUS_ENTITY_TYPE / AMBIGUOUS_ID / FAILURE)
    unresolved_synonym_counts_by_status: dict = field(
        default_factory=lambda: {
            GroupStatus.AMBIGUOUS_ENTITY_TYPE: Counter(),
            GroupStatus.AMBIGUOUS_ID: Counter(),
            GroupStatus.FAILURE: Counter(),
        }
    )


    def record_input_hit(self, hit: CandidateHit) -> None:
        self.input_hits += 1
        self.input_entity_type_counts[hit.entity_type] += 1
        self.input_synonym_type_counts[hit.synonym_type] += 1

    def record_group(self, group: HitGroup, emitted_hits: int) -> None:
        self.total_groups += 1
        group_size = len(group.hits)
        self.group_size_counts[group_size] += 1
        self.group_status_counts[group.group_status] += 1
        self.emitted_hits_per_group_counts[emitted_hits] += 1
        resolved = group.group_status in RESOLVED_STATUSES

        needs_disambiguation = group.is_ambiguous() or group.contains_any_abbreviation()
        if needs_disambiguation:
            self.multi_candidate_groups += 1
            if resolved:
                self.multi_candidate_resolved += 1

        synonym_key = self._synonym_key(group)
        if synonym_key is None:
            return

        if group.is_ambiguous():
            self.ambiguous_synonym_counts[synonym_key] += 1

        if resolved:
            self.resolved_synonym_counts[synonym_key] += 1
            if group.group_status == GroupStatus.PARTIALLY_RESOLVED:
                self.partially_resolved_synonym_counts[synonym_key] += 1
        elif group.group_status in self.unresolved_synonym_counts_by_status:
            self.unresolved_synonym_counts_by_status[group.group_status][synonym_key] += 1

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
        """Fraction of ALL groups that ended up resolved (any of RESOLVED_STATUSES)."""
        if self.total_groups == 0:
            return 0.0
        resolved = sum(self.group_status_counts[status] for status in RESOLVED_STATUSES)
        return resolved / self.total_groups

    @property
    def multi_candidate_resolution_rate(self) -> float:
        """Fraction of groups that needed disambiguation (ambiguous or contained an
        abbreviation) that ended up resolved, as opposed to AMBIGUOUS/FAILURE."""
        if self.multi_candidate_groups == 0:
            return 0.0
        return self.multi_candidate_resolved / self.multi_candidate_groups


    def top_ambiguous_synonyms(self, n: int = 10):
        return self.ambiguous_synonym_counts.most_common(n)

    def top_resolved_synonyms(self, n: int = 10):
        return self.resolved_synonym_counts.most_common(n)

    def top_partially_resolved_synonyms(self, n: int = 10):
        return self.partially_resolved_synonym_counts.most_common(n)

    def top_unresolved_synonyms(self, n: int = 10, status: Optional[GroupStatus] = None):
        """Top unresolved synonyms. Pass a specific GroupStatus (e.g.
        GroupStatus.AMBIGUOUS_ENTITY_TYPE) to isolate one failure mode, or
        omit to combine all unresolved statuses."""
        if status is not None:
            return self.unresolved_synonym_counts_by_status[status].most_common(n)
        combined = Counter()
        for counts in self.unresolved_synonym_counts_by_status.values():
            combined.update(counts)
        return combined.most_common(n)

    def print_summary(self, top_n: int = 10) -> None:
        def emit(line: str = "") -> None:
            #print(line)
            logger.info(line)

        emit(f"{'--- HitProcessor Summary ---':^40}")
        emit(f"Articles Processed:      {self.articles_processed}")
        emit(f"Input Hits:              {self.input_hits}")
        emit(f"Output Hits:             {self.output_hits}")
        emit(f"Hits Collapsed:          {self.hits_collapsed}")
        emit(f"Total Groups:            {self.total_groups}")
        emit(f"Multi-Candidate Groups:  {self.multi_candidate_groups}")
        emit(f"Resolution Rate:         {self.resolution_rate:.2%}")
        emit(f"Multi-Candidate Res. Rate: {self.multi_candidate_resolution_rate:.2%}")

        emit()
        emit("Group Size Distribution:")
        for size, count in sorted(self.group_size_counts.items()):
            emit(f"  size={size:<3}: {count}")

        emit()
        emit("Emitted Hits per Group:")
        for n_hits, count in sorted(self.emitted_hits_per_group_counts.items()):
            emit(f"  hits={n_hits:<3}: {count}")

        emit()
        emit("Input Hits by Entity Type:")
        for entity, count in self.input_entity_type_counts.items():
            emit(f"  {entity:<20}: {count}")

        emit()
        emit("Input Hits by Synonym Type:")
        for syn_type, count in self.input_synonym_type_counts.items():
            emit(f"  {syn_type:<20}: {count}")

        emit()
        emit("Groups by Resolution Status:")
        for status, count in self.group_status_counts.items():
            emit(f"  {status:<20}: {count}")

        emit()
        emit(f"Top {top_n} Synonyms Flagged Ambiguous:")
        for synonym, count in self.top_ambiguous_synonyms(top_n):
            emit(f"  {synonym!r:<30}: {count}")

        emit()
        emit(f"Top {top_n} Synonyms Successfully Resolved:")
        for synonym, count in self.top_resolved_synonyms(top_n):
            emit(f"  {synonym!r:<30}: {count}")

        top_partial = self.top_partially_resolved_synonyms(top_n)
        if top_partial:
            emit()
            emit(f"Top {top_n} Synonyms Partially Resolved (some type parts unresolved):")
            for synonym, count in top_partial:
                emit(f"  {synonym!r:<30}: {count}")

        emit()
        emit(f"Top {top_n} Synonyms Remaining Unresolved (all statuses):")
        for synonym, count in self.top_unresolved_synonyms(top_n):
            emit(f"  {synonym!r:<30}: {count}")

        for status in self.unresolved_synonym_counts_by_status:
            top = self.top_unresolved_synonyms(top_n, status=status)
            if not top:
                continue
            emit()
            emit(f"Top {top_n} Synonyms Unresolved due to {status.value}:")
            for synonym, count in top:
                emit(f"  {synonym!r:<30}: {count}")