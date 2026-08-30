from abc import ABC, abstractmethod
import re
import logging
from typing import Iterable, Optional
from dataclasses import dataclass
from textmining.models import CandidateHit, NormalizedHit, NormalizationResult, NormalizationTargetType, NormalizationStatus, NormalizationContext
from textmining.normalization_resources import MirNormalizationResources

logger = logging.getLogger(__name__)

@dataclass
class MirNormalizationCandidate:
    normalization: NormalizationResult
    prefix: Optional[str] = None
    suffix: Optional[str] = None

class EntityNormalizer(ABC):
    @abstractmethod
    def normalize(self, hit: CandidateHit, normalization_context: NormalizationContext) -> Iterable['NormalizedHit']:
        ...

class DefaultNormalizer(EntityNormalizer):
    def normalize(self, hit: CandidateHit, normalization_context: NormalizationContext) -> Iterable['NormalizedHit']:
        norm_result = NormalizationResult(NormalizationStatus.NORMALIZED, hit.entity_id)
        return [NormalizedHit.from_candidate(hit, norm_result)]

class MirNormalizer(EntityNormalizer):
    _SUFFIX_CLEANER = re.compile(r"[^a-zA-Z0-9*-]+")
    
    def __init__(self,
                 resources: MirNormalizationResources):
        super().__init__()  
        self.resources = resources
        logger.info("Initialized MirNormalizer")
        
    def normalize(self, hit: CandidateHit, normalization_context: NormalizationContext) -> Iterable['NormalizedHit']:
        buffer_out = []
        normalized_prefix = self._normalize_mirna_prefix(hit.prefix.lower())
        combined_suffix = self._normalize_mirna_suffix(hit.suffix.lower())
        mirna_body = MirIdMapper.resolve_token(hit.entity_id)
        sentence_id = hit.sentence_id

        if mirna_body is None:
            logger.error("Unresolved miRNA entity id=%s at sentence=%s", hit.entity_id, sentence_id)
            raise ValueError(f'Unresolved miRNA entity id: {hit.entity_id}')

        # NO SUFFIX = FILTER
        if not combined_suffix and mirna_body != 'bantam':
            logger.debug(
                "Filtering hit with no suffix: entity_id=%s, sentence=%s, raw_text=%r",
                hit.entity_id, sentence_id, hit.raw_text,
            )
            normalized_hit = NormalizedHit.from_candidate(hit,  NormalizationResult(NormalizationStatus.FILTERED))
            buffer_out.append(normalized_hit)
            return buffer_out

        norm_candidates: list[MirNormalizationCandidate] = []
        if not normalized_prefix:
            logger.debug("No prefix for entity_id=%s; attempting inference (sentence=%s)", hit.entity_id, sentence_id)
            norm_candidates.extend(self._resolve_missing_prefix(sentence_id=sentence_id,
                                                                mirna_body=mirna_body,
                                                                mirna_suffix=combined_suffix,
                                                                normalization_context=normalization_context)
            )
        else:
            norm_result = self._map_to_accession(prefix=normalized_prefix,
                                                  mirna_body=mirna_body,
                                                  suffix=combined_suffix)
            norm_candidates.append(MirNormalizationCandidate(normalization=norm_result, 
                                                             prefix=normalized_prefix,
                                                             suffix=combined_suffix))
            
        statuses = [c.normalization.status for c in norm_candidates]
        logger.debug("Normalized hit entity_id=%s -> %d candidate(s), statuses=%s", hit.entity_id, len(norm_candidates), statuses)
       
        for norm_candidate in norm_candidates:
            buffer_out.append(NormalizedHit.from_candidate(hit, 
                                                           normalization=norm_candidate.normalization, 
                                                           prefix=norm_candidate.prefix, 
                                                           suffix=norm_candidate.suffix))
    
        return buffer_out
    
    # If prefix is missing, try to infer it, unless the hit is a family hit
    def _resolve_missing_prefix(self, sentence_id, mirna_body, mirna_suffix, normalization_context: NormalizationContext) -> Iterable[MirNormalizationCandidate]:
        mirna_with_suffix = mirna_body + (mirna_suffix or '')
        implied_prefixes = self._get_implied_prefixes(normalization_context.get_taxon_relevance().keys())
        mirbase_prefixes = self.resources.mirna_2_prefix.get(mirna_with_suffix, None)
        family_accession = self.resources.family_normalizer.get(mirna_with_suffix, None)

        no_prefix_overlap = not mirbase_prefixes or not (mirbase_prefixes & implied_prefixes)
        if family_accession and (no_prefix_overlap or self._is_family_sentence(sentence_id=sentence_id,
                                                                                  normalization_context=normalization_context)):
            logger.debug(
                "Falling back to family accession=%s for mirna=%s: mirbase_prefixes=%s, implied_prefixes=%s, no_prefix_overlap=%s, sentence=%s",
                family_accession, mirna_with_suffix, mirbase_prefixes, implied_prefixes, no_prefix_overlap, sentence_id,
            )
            norm_result = NormalizationResult(status=NormalizationStatus.FALLBACK,
                                              normalized_id=family_accession,
                                              target_type=NormalizationTargetType.MIR_FAMILY)
            return [MirNormalizationCandidate(normalization=norm_result)]
        elif not mirbase_prefixes:
            norm_result = NormalizationResult(NormalizationStatus.UNKNOWN_ENTITY)
            return [MirNormalizationCandidate(normalization=norm_result)]
        else:
            return self._resolve_by_prefix_intersection(mirna_body=mirna_body,
                                                        suffix=mirna_suffix,
                                                        implied_prefixes=implied_prefixes,
                                                        mirbase_prefixes=mirbase_prefixes)
                
    # This returns the set of prefixes mentioned in the article
    def _get_implied_prefixes(self, relevant_taxons) -> set:
        return {self.resources.taxon_2_prefix[tax_id] for tax_id in relevant_taxons if tax_id in self.resources.taxon_2_prefix}

    # Try to infer the missing prefix by the intersection of implied prefixes and allowed prefixes
    def _resolve_by_prefix_intersection(self, mirna_body, suffix, implied_prefixes, mirbase_prefixes) -> Iterable[MirNormalizationCandidate]:
        matches = []
        possible_prefixes = implied_prefixes & mirbase_prefixes
        if not possible_prefixes:
            logger.debug(
                "Prefix intersection empty for mirna_body=%s: implied=%s, mirbase=%s",
                mirna_body, implied_prefixes, mirbase_prefixes,
            )
            norm_result = NormalizationResult(NormalizationStatus.UNKNOWN_ENTITY)
            matches.append(MirNormalizationCandidate(normalization=norm_result))
        else:
            for prefix in possible_prefixes:
                normalization_result = self._map_to_accession(prefix=prefix, mirna_body=mirna_body, suffix=suffix)
                matches.append(MirNormalizationCandidate(normalization=normalization_result,prefix=prefix, suffix=suffix))
        return matches
    
    # Given the full mirna name, try to map to a unique accession (MIPF, MI, MIMAT)
    def _map_to_accession(self, prefix, mirna_body, suffix) -> NormalizationResult:
        accession = None
        status = None
        target_type = None
        is_dead = False
        combined_mirna = MirNormalizer._join_parts(prefix, mirna_body + (suffix or ''))
        if combined_mirna in self.resources.ambiguous_precursors or combined_mirna in self.resources.ambiguous_mature:
            status = NormalizationStatus.IN_BLACKLIST
        else:
            precursor_data = self.resources.precursor_normalizer.get(combined_mirna, None)
            mature_data = self.resources.mature_normalizer.get(combined_mirna, None)
            if precursor_data and mature_data:
                # Fallback to precursor
                status = NormalizationStatus.FALLBACK
                accession = precursor_data['accession']
                target_type = NormalizationTargetType.MIR_PRECURSOR
                is_dead = precursor_data['dead']
            elif not precursor_data and not mature_data:
                status = NormalizationStatus.UNKNOWN_ENTITY
            else:
                data = precursor_data or mature_data
                is_dead = data['dead']
                accession = data['accession']
                target_type = NormalizationTargetType.MIR_PRECURSOR if precursor_data else NormalizationTargetType.MIR_MATURE
                status = NormalizationStatus.NORMALIZED
        return NormalizationResult(status, accession, target_type, is_dead)
    
    # Very simple heuristic for checking if a mirna hit is a family mirna hit
    def _is_family_sentence(self, sentence_id, normalization_context: NormalizationContext):
        return 'famil' in normalization_context.fetch_sentence(sentence_id=sentence_id).lower()
                    
    def _normalize_mirna_prefix(self, prefix):
        matched_prefix = self.resources.prefix_regex.search(prefix)
        if matched_prefix:
            return matched_prefix.group(1)
        else:
            return None

    # Preserves whether the raw text actually had a delimiter (e.g. "hsa-mir-21")
    # or fused the body directly into the digits (e.g. "zma-mir408a", the plant
    # naming convention) - miRBase's own IDs differ the same way, so the
    # delimiter can't just be normalized away without breaking dict lookups.
    def _normalize_mirna_suffix(self, suffix) -> Optional[str]:
        match = self.resources.suffix_regex.search(suffix)
        if not match:
            return None
        leading = match.group(1) or ''
        had_delimiter = bool(re.match(r'^[-_x]', leading))
        body = re.sub(r'^[-_x]', '', leading)
        combined = body + (match.group(2) or '')
        combined = MirNormalizer._SUFFIX_CLEANER.sub('-', combined).rstrip('-')
        if not combined:
            return None
        return ('-' + combined) if had_delimiter else combined
    
    @staticmethod
    def _join_parts(*parts: Optional[str]) -> str:
        return '-'.join(p for p in parts if p)

class MirIdMapper:
    _id_to_token = {
            'MIR_REGEX_1': 'mir',
            'MIR_REGEX_2': 'let',
            'MIR_REGEX_3': 'lin',
            'MIR_REGEX_4': 'bantam',
            'MIR_REGEX_5': 'lsy',
            'MIR_REGEX_6': 'iab',
            'MIR_REGEX_7': 'mir-iab'
        }

    @staticmethod
    def resolve_token(entity_id: str) -> str | None:
        return MirIdMapper._id_to_token.get(entity_id)


def normalized_successfully(hit: NormalizedHit) -> bool:
    if not hit.normalization:
        raise ValueError(f'Tried to group hit that was not normalized! Hit: {hit}')
    return hit.normalization.status not in (NormalizationStatus.UNKNOWN_ENTITY, NormalizationStatus.FILTERED)