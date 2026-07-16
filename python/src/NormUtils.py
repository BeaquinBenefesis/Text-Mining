from abc import ABC, abstractmethod
from collections import deque
import re
import json
import pandas as pd
from ArticleUtils import ArticleContext


class EntityNormalizer(ABC):
    @abstractmethod
    def normalize(self, hit: dict, article_context: ArticleContext) -> deque[dict]:
        ...

class DefaultNormalizer(EntityNormalizer):
    def normalize(self, hit: dict, article_context: ArticleContext) -> deque[dict]:
        return deque([hit])

class MirNormalizer(EntityNormalizer):
    _SUFFIX_CLEANER = re.compile(r"[^a-zA-Z0-9-]+")
    
    def __init__(self,
                 sentence_reader,
                 mirna_taxons_path,
                 mirna_2_prefix_path,
                 family_normalizer_path,
                 precursor_normalizer_path,
                 mature_normalizer_path,
                 precursor_ambiguous_path,
                 mature_ambiguous_path):
        super().__init__()
        
        # SENTENCE CONTEXT
        self.sentence_reader = sentence_reader
                
        # PREFIX NORMALIZATION
        with open(mirna_2_prefix_path, 'r') as mirna_2_prefix_dict:
            mirna_2_prefix_raw = json.load(mirna_2_prefix_dict)
            self.mirna_2_prefix = {key: set(prefix_list) for key, prefix_list in mirna_2_prefix_raw.items()}
        
        # NORMALIZATION (MAP TO ACCESSION)
        with open(family_normalizer_path, 'r') as fam_dict:
            self.family_normalizer = json.load(fam_dict)
        with open(precursor_normalizer_path, 'r') as precursor_dict:
            self.precursor_normalizer = json.load(precursor_dict)
        with open(mature_normalizer_path, 'r') as mature_dict:
            self.mature_normalizer = json.load(mature_dict)
        
        # AMBIGUOUS MIRNA IDS (precursor and mature)
        self.ambiguous_precursors = set(pd.read_csv(precursor_ambiguous_path, sep='\t')['mirna_name'])
        self.ambiguous_mature = set(pd.read_csv(mature_ambiguous_path, sep='\t')['mirna_name'])
        
        # TAXONS
        mirna_taxons = pd.read_csv(mirna_taxons_path, sep='\t')
        self.relevant_taxons = set(mirna_taxons['id'])
        self.taxon_2_prefix = dict(zip(mirna_taxons['id'], mirna_taxons['prefix']))
        
        # REGEX
        self.prefix_regex = re.compile(f"((?:{'|'.join(list(mirna_taxons['prefix']))}))[-‐ ]$")
        self.suffix_regex = re.compile(self._build_mirna_suffix_pattern())
    
    def normalize(self, hit: dict, article_context: ArticleContext) -> deque[dict]:
        buffer_out = deque()
        normalized_prefix = self._normalize_mirna_prefix(hit['prefix'].lower())
        suffix_groups = self._normalize_mirna_suffix(hit['suffix'].lower())
        mirna_body = MirIdMapper.resolve_token(hit['synonym_id'])

        # A valid mirna has to have at least a valid suffix
        # TODO: Modify this for bantam
        if not suffix_groups and not mirna_body == 'bantam':
            return buffer_out
        
        mirna_with_suffix = None
        if suffix_groups:
            normalized_suffix, mature_part = suffix_groups
            combined_suffix = normalized_suffix + mature_part
            combined_suffix = MirNormalizer._SUFFIX_CLEANER.sub('-', combined_suffix)
            mirna_with_suffix = mirna_body + combined_suffix
            hit['suffix'] = combined_suffix
        else:
            mirna_with_suffix = mirna_body

        if not normalized_prefix:
            taxon_relevance = article_context.get_taxon_relevance()
            buffer_out.extend(self._resolve_missing_prefix(hit['sentence_id'], mirna_with_suffix, taxon_relevance.keys(), hit))
        else:
            hit['prefix'] = normalized_prefix
            combined = normalized_prefix + mirna_with_suffix
            hit['accession'], hit['status'] = self._map_to_accession(combined)
            buffer_out.append(hit)
    
        return buffer_out
    
    def _resolve_missing_prefix(self, sentence_id, mirna_with_suffix, relevant_taxons, hit) -> deque[dict]:
        matches = deque()
        implied_prefixes = self._get_implied_prefixes(relevant_taxons)
        mirbase_prefixes = self.mirna_2_prefix.get(mirna_with_suffix, None)
        family_accession = self.family_normalizer.get(mirna_with_suffix, None)
        
        if family_accession and (not mirbase_prefixes or self._is_family_sentence(sentence_id)):
            hit['status'] = 'MAPPED_TO_FAMILY'
            hit['accession'] = family_accession
            matches.append(hit)
        elif not mirbase_prefixes:
            hit['status'] = 'NOT_IN_MIRBASE'
            matches.append(hit)
        else:
            matches.extend(self._resolve_by_prefix_intersection(hit, mirna_with_suffix, implied_prefixes, mirbase_prefixes))
        return matches
    
    def _get_implied_prefixes(self, relevant_taxons) -> set:
        return {self.taxon_2_prefix[tax_id] for tax_id in relevant_taxons if tax_id in self.taxon_2_prefix}

    def _resolve_by_prefix_intersection(self, hit, mirna_with_suffix, implied_prefixes, mirbase_prefixes) -> list[dict]:
        matches = deque()
        possible_prefixes = implied_prefixes & mirbase_prefixes
        if not possible_prefixes:
            hit['status'] = 'FAILURE'
            matches.append(hit)
        else:
            for prefix in possible_prefixes:
                combined = prefix + '-' + mirna_with_suffix
                copy = hit.copy()
                copy['prefix'] = prefix
                copy['accession'], copy['status'] = self._map_to_accession(combined)
                matches.append(copy)
        return matches
    
    def _map_to_accession(self, combined_mirna):
        accession = None
        status = None
        if combined_mirna in self.ambiguous_precursors or combined_mirna in self.ambiguous_mature:
            status = 'AMBIGUOUS_ACCESSION'
        else:
            precursor_data = self.precursor_normalizer.get(combined_mirna, None)
            mature_data = self.mature_normalizer.get(combined_mirna, None)
            if precursor_data and mature_data:
                status = 'AMBIGUOUS_TYPE'
            elif not precursor_data and not mature_data:
                status = 'NOT_IN_MIRBASE'
            else:
                data = precursor_data or mature_data
                is_dead: bool = data['dead']
                accession = data['accession'] 
                status = 'DEAD' if is_dead else ('MAPPED_TO_PRECURSOR' if precursor_data else 'MAPPED_TO_MATURE')
        return accession, status
    
    def _is_family_sentence(self, sentence_id):
        return 'famil' in self.sentence_reader.fetch_text(sentence_id)
                    
    def _normalize_mirna_prefix(self, prefix):
        matched_prefix = self.prefix_regex.search(prefix)
        if matched_prefix:
            return matched_prefix.group(0)
        else:
            return None

    def _normalize_mirna_suffix(self, suffix):
        match = self.suffix_regex.search(suffix)
        if match:
            return match.group(1) if match.group(1) else '', match.group(2) if match.group(2) else ''
        else:
            return None

    def _build_mirna_suffix_pattern(self):
        leading = r"[-_x]?"
        let_prefix = r"[a-zA-Z]{0,5}"
        number = r"[0-9]+"
        let_suffix  = r"(?:[a-zA-Z]{1,2}[0-9]*)*"
        segment =  rf"(?:{let_prefix}{number}{let_suffix})"
        more_segs = rf"(?:[-_](?![35][pP]){segment})*"
        strand = r"(\*|[-/]?[35][pP])?"
        group1 = rf"({leading}{segment}{more_segs})"
        return rf"^{group1}{strand}"


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

