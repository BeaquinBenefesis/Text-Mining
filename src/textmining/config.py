from dataclasses import dataclass, field
from pathlib import Path
import textmining.resources as res 
from textmining.types import HitType
from textmining.paths import OUTPUTS_DIR


@dataclass
class DiseasePipelineConfig:
    output_name: str
    n_tasks: int = 50
    sentence_pattern: str = str(res.CORPUS_DIR / "*.sent")
    synonyms: dict = field(default_factory=lambda: {HitType.DISEASE: [res.DISEASE_SYNS]})
    abbrev_synonyms: dict = field(default_factory=lambda: {HitType.DISEASE: [res.DISEASE_ABBREV]})
    output_dir: Path = OUTPUTS_DIR / "disease"
    abbrev: bool = True
    word_char: str = "SYNONYMS"
    disease_obo_path: Path = res.MONDO_OBO
    
    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        res.validate_resource(self.disease_obo_path)
        for paths in self.synonyms.values():
            for path in paths:
                res.validate_resource(path)
        for paths in self.abbrev_synonyms.values():
            for path in paths:
                res.validate_resource(path)


@dataclass
class ExistingSyngrepDiseaseConfig:
    output_name: str
    hits_path: Path
    synfile_map_path: Path
    synfile_type_map_path: Path
    output_dir: Path = OUTPUTS_DIR / "disease"
    disease_obo_path: Path = res.MONDO_OBO
    
    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        res.validate_resource(self.hits_path)
        res.validate_resource(self.synfile_map_path)
        res.validate_resource(self.synfile_type_map_path)
        res.validate_resource(self.disease_obo_path)

    
@dataclass
class MirnaPipelineConfig:
    output_name: str
    n_tasks: int = 50
    sentence_pattern: str = str(res.CORPUS_DIR / "*.sent")
    synonyms: dict = field(default_factory=lambda: {
        HitType.MIR: [res.MIR_SYNS],
        HitType.TAXON: [res.SPECIES_SYNS, res.SPECIES_FROM_CL_SYNS],
    })
    output_dir: Path = OUTPUTS_DIR / "mirna"
    abbrev: bool = False
    within_word: list = field(default_factory=lambda: [res.MIR_SYNS.name])
    sentence_path: Path = res.SENTENCES_SORTED
    families_path: Path = res.MIR_FAMILY_PATH
    precursor_path: Path = res.MIR_PRECURSOR_PATH
    mature_path: Path = res.MIR_MATURE_PATH
    parent_to_child_path: Path = res.MIR_PARENT_TO_CHILD_PATH
    mirna_taxons_path: Path = res.MIR_TAXONS_PATH
    mirna_to_prefix_path: Path = res.MIR_TO_PREFIX_PATH
    family_norm_path: Path = res.MIR_FAMILY_NORM_PATH
    precursor_norm_path: Path = res.MIR_PRECURSOR_NORM_PATH
    mature_norm_path: Path = res.MIR_MATURE_NORM_PATH
    taxon_obo_path: Path = res.TAXON_OBO
    precursor_ambi_path: Path = res.MIR_PRECURSOR_AMBI_PATH
    mature_ambi_path: Path = res.MIR_MATURE_AMBI_PATH
    
    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        res.validate_resource(self.sentence_path)

        for paths in self.synonyms.values():
            for path in paths:
                res.validate_resource(path)

        for path in [
            self.families_path,
            self.precursor_path,
            self.mature_path,
            self.parent_to_child_path,
            self.mirna_taxons_path,
            self.mirna_to_prefix_path,
            self.family_norm_path,
            self.precursor_norm_path,
            self.mature_norm_path,
            self.precursor_ambi_path,
            self.mature_ambi_path,
            self.taxon_obo_path
        ]:
            res.validate_resource(path)

@dataclass
class ExistingSyngrepMirnaConfig:
    output_name: str
    hits_path: Path
    synfile_map_path: Path
    synfile_type_map_path: Path
    output_dir: Path = OUTPUTS_DIR / "mirna"
    sentence_path: Path = res.SENTENCES_SORTED
    families_path: Path = res.MIR_FAMILY_PATH
    precursor_path: Path = res.MIR_PRECURSOR_PATH
    mature_path: Path = res.MIR_MATURE_PATH
    parent_to_child_path: Path = res.MIR_PARENT_TO_CHILD_PATH
    mirna_taxons_path: Path = res.MIR_TAXONS_PATH
    mirna_to_prefix_path: Path = res.MIR_TO_PREFIX_PATH
    family_norm_path: Path = res.MIR_FAMILY_NORM_PATH
    precursor_norm_path: Path = res.MIR_PRECURSOR_NORM_PATH
    mature_norm_path: Path = res.MIR_MATURE_NORM_PATH
    taxon_obo_path: Path = res.TAXON_OBO
    precursor_ambi_path: Path = res.MIR_PRECURSOR_AMBI_PATH
    mature_ambi_path: Path = res.MIR_MATURE_AMBI_PATH

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        for path in [
            self.hits_path,
            self.synfile_map_path,
            self.synfile_type_map_path,
            self.sentence_path,
            self.families_path,
            self.precursor_path,
            self.mature_path,
            self.parent_to_child_path,
            self.mirna_taxons_path,
            self.mirna_to_prefix_path,
            self.family_norm_path,
            self.precursor_norm_path,
            self.mature_norm_path,
            self.precursor_ambi_path,
            self.mature_ambi_path,
            self.taxon_obo_path
        ]:
            res.validate_resource(path)
