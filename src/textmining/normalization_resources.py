from dataclasses import dataclass
from typing import Dict, Set
import re
import json
import pandas as pd

@dataclass(frozen=True)
class MirNormalizationResources:
    mirna_2_prefix: Dict[str, Set[str]]
    family_normalizer: Dict[str, str]
    precursor_normalizer: Dict[str, dict]
    mature_normalizer: Dict[str, dict]
    ambiguous_precursors: Set[str]
    ambiguous_mature: Set[str]
    relevant_taxons: Set[str]
    taxon_2_prefix: Dict[int, str]
    prefix_regex: re.Pattern
    suffix_regex: re.Pattern
    
class MirResourceLoader:
    @staticmethod
    def load(
        mirna_taxons_path,
        mirna_2_prefix_path,
        family_normalizer_path,
        precursor_normalizer_path,
        mature_normalizer_path,
        precursor_ambiguous_path,
        mature_ambiguous_path,
    ) -> MirNormalizationResources:
        with open(mirna_2_prefix_path, "r") as f:
            mirna_2_prefix_raw = json.load(f)
            mirna_2_prefix = {
                key: set(prefixes) for key, prefixes in mirna_2_prefix_raw.items()
            }
        with open(family_normalizer_path, "r") as f:
            family_normalizer = json.load(f)
        with open(precursor_normalizer_path, "r") as f:
            precursor_normalizer = json.load(f)
        with open(mature_normalizer_path, "r") as f:
            mature_normalizer = json.load(f)
        ambiguous_precursors = set(
            pd.read_csv(precursor_ambiguous_path, sep="\t")["mirna_name"]
        )
        ambiguous_mature = set(
            pd.read_csv(mature_ambiguous_path, sep="\t")["mirna_name"]
        )
        mirna_taxons = pd.read_csv(mirna_taxons_path, sep="\t")
        relevant_taxons = set(mirna_taxons["id"])
        taxon_2_prefix = dict(zip(mirna_taxons["id"], mirna_taxons["prefix"]))
        prefix_regex = re.compile(
            f"((?:{'|'.join(list(mirna_taxons['prefix']))}))[-‐ ]$"
        )
        suffix_regex = re.compile(MirResourceLoader._build_mirna_suffix_pattern())
        return MirNormalizationResources(
            mirna_2_prefix=mirna_2_prefix,
            family_normalizer=family_normalizer,
            precursor_normalizer=precursor_normalizer,
            mature_normalizer=mature_normalizer,
            ambiguous_precursors=ambiguous_precursors,
            ambiguous_mature=ambiguous_mature,
            relevant_taxons=relevant_taxons,
            taxon_2_prefix=taxon_2_prefix,
            prefix_regex=prefix_regex,
            suffix_regex=suffix_regex,
        )
    
    @staticmethod
    def _build_mirna_suffix_pattern():
        leading = r"[-_x]?"
        let_prefix = r"[a-zA-Z]{0,5}"
        number = r"[0-9]+"
        let_suffix  = r"(?:[a-zA-Z]{1,2}[0-9]*)*"
        segment =  rf"(?:{let_prefix}{number}{let_suffix})"
        more_segs = rf"(?:[-_](?![35][pP]){segment})*"
        strand = r"(\*|[-/]?[35][pP])?"
        group1 = rf"({leading}{segment}{more_segs})"
        return rf"^{group1}{strand}"
