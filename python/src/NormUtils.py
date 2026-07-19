from abc import ABC, abstractmethod
from collections import deque
import re
import json
import pandas as pd
from ArticleUtils import ArticleContext
from models import (NormalizedHit, NormalizationResult, NormalizationTargetType, NormalizationStatus)
from typing import Iterable
from resources import MirResourceLoader, MirNormalizationResources
from sentence_utils import SentenceReader
from dataclasses import dataclass, field

class EntityNormalizer(ABC):
    @abstractmethod
    def normalize(self, hit: NormalizedHit, article_context: ArticleContext) -> Iterable['NormalizedHit']:
        ...

class DefaultNormalizer(EntityNormalizer):
    def normalize(self, hit: NormalizedHit, article_context: ArticleContext) -> Iterable['NormalizedHit']:
        hit.normalization = NormalizationResult(NormalizationStatus.NORMALIZED, hit.synonym_id)
        return deque([hit])

class MirNormalizer(EntityNormalizer):
    _SUFFIX_CLEANER = re.compile(r"[^a-zA-Z0-9-]+")
    
    def __init__(self,
                 sentence_reader: SentenceReader,
                 resources: MirNormalizationResources):
        super().__init__()  
        self.sentence_reader = sentence_reader
        self.resources = resources
        
    def normalize(self, hit: NormalizedHit, article_context: ArticleContext) -> Iterable['NormalizedHit']:
        buffer_out = deque()
        normalized_prefix = self._normalize_mirna_prefix(hit.prefix.lower())
        suffix_groups = self._normalize_mirna_suffix(hit.suffix.lower())
        mirna_body = MirIdMapper.resolve_token(hit.synonym_id)
        
        if mirna_body is None:
            raise ValueError(f'Unresolved miRNA synonym id: {hit.synonym_id}')

        # NO SUFFIX = FILTER
        if not suffix_groups and mirna_body != 'bantam':
            hit.normalization = NormalizationResult(NormalizationStatus.FILTERED)
            buffer_out.append(hit)
            return buffer_out
        
        # SUFFIX FOUND
        mirna_with_suffix = None
        if suffix_groups:
            normalized_suffix, mature_part = suffix_groups
            combined_suffix = normalized_suffix + mature_part
            combined_suffix = MirNormalizer._SUFFIX_CLEANER.sub('-', combined_suffix)
            mirna_with_suffix = mirna_body + combined_suffix
            hit.suffix = combined_suffix
        else:
            mirna_with_suffix = mirna_body

        if not normalized_prefix:
            taxon_relevance = article_context.get_taxon_relevance()
            buffer_out.extend(self._resolve_missing_prefix(hit.sentence_id, 
                                                           mirna_with_suffix, 
                                                           taxon_relevance.keys(), 
                                                           hit))
        else:
            hit.prefix = normalized_prefix
            combined = f"{normalized_prefix}-{mirna_with_suffix}"
            hit.normalization = self._map_to_accession(combined)
            buffer_out.append(hit)
    
        return buffer_out
    
    # If prefix is missing, try to infer it, unless the hit is a family hit
    def _resolve_missing_prefix(self, sentence_id, mirna_with_suffix, relevant_taxons, hit: NormalizedHit) -> Iterable['NormalizedHit']:
        matches = deque()
        implied_prefixes = self._get_implied_prefixes(relevant_taxons)
        mirbase_prefixes = self.resources.mirna_2_prefix.get(mirna_with_suffix, None)
        family_accession = self.resources.family_normalizer.get(mirna_with_suffix, None)
        
        if family_accession and (not mirbase_prefixes or self._is_family_sentence(sentence_id)):
            hit.normalization = NormalizationResult(NormalizationStatus.FALLBACK, 
                                                    family_accession, 
                                                    NormalizationTargetType.MIR_FAMILY)
            matches.append(hit)
        elif not mirbase_prefixes:
            hit.normalization = NormalizationResult(NormalizationStatus.UNRESOLVED)
            matches.append(hit)
        else:
            matches.extend(self._resolve_by_prefix_intersection(hit, 
                                                                mirna_with_suffix, 
                                                                implied_prefixes, 
                                                                mirbase_prefixes))
        return matches
    
    # This returns the set of prefixes mentioned in the article
    def _get_implied_prefixes(self, relevant_taxons) -> set:
        return {self.resources.taxon_2_prefix[tax_id] for tax_id in relevant_taxons if tax_id in self.resources.taxon_2_prefix}

    # Try to infer the missing prefix by the intersection of implied prefixes and allowed prefixes
    def _resolve_by_prefix_intersection(self, hit: NormalizedHit, mirna_with_suffix, implied_prefixes, mirbase_prefixes) -> Iterable['NormalizedHit']:
        matches = deque()
        possible_prefixes = implied_prefixes & mirbase_prefixes
        if not possible_prefixes:
            hit.normalization = NormalizationResult(NormalizationStatus.UNRESOLVED)
            matches.append(hit)
        else:
            for prefix in possible_prefixes:
                combined = prefix + '-' + mirna_with_suffix
                normalization_result = self._map_to_accession(combined)
                copy = hit.copy(prefix=prefix, normalization=normalization_result)
                matches.append(copy)
        return matches
    
    # Given the full mirna name, try to map to a unique accession (MIPF, MI, MIMAT)
    def _map_to_accession(self, combined_mirna) -> NormalizationResult:
        accession = None
        status = None
        target_type = None
        is_dead = False
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
                status = NormalizationStatus.UNRESOLVED
            else:
                data = precursor_data or mature_data
                is_dead = data['dead']
                accession = data['accession']
                target_type = NormalizationTargetType.MIR_PRECURSOR if precursor_data else NormalizationTargetType.MIR_MATURE
                status = NormalizationStatus.NORMALIZED
        return NormalizationResult(status, accession, target_type, is_dead)
    
    # Very simple heuristic for checking if a mirna hit is a family mirna hit
    def _is_family_sentence(self, sentence_id):
        return 'famil' in self.sentence_reader.fetch_text(sentence_id).lower()
                    
    def _normalize_mirna_prefix(self, prefix):
        matched_prefix = self.resources.prefix_regex.search(prefix)
        if matched_prefix:
            return matched_prefix.group(1)
        else:
            return None

    def _normalize_mirna_suffix(self, suffix):
        match = self.resources.suffix_regex.search(suffix)
        if match:
            return match.group(1) if match.group(1) else '', match.group(2) if match.group(2) else ''
        else:
            return None

class MirIdMapper:
    _id_to_token = {
            'MIR_REGEX_1': 'mir',
            'MIR_REGEX_2': 'let',
            'MIR_REGEX_3': 'lin',
            'MIR_REGEX_4': 'bantam',
            'MIR_REGEX_5': 'lsy',
            'MIR_REGEX_6': 'iab'
        }

    @staticmethod
    def resolve_token(synonym_id: str) -> str | None:
        return MirIdMapper._id_to_token.get(synonym_id)
