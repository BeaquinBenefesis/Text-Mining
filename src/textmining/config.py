from dataclasses import dataclass, field
from pathlib import Path
import textmining.resources as res
from textmining.types import HitType
from textmining.paths import OUTPUTS_DIR


def output_path(default: Path) -> Path:
    return field(default=default, metadata={"skip_validation": True})


class ValidatedConfig:

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        res.validate_paths(self)


@dataclass
class DiseasePipelineConfig(ValidatedConfig):
    output_name: str
    n_tasks: int = 50
    sentence_pattern: str = str(res.CORPUS_DIR / "*.sent")
    synonyms: dict = field(default_factory=lambda: {HitType.DISEASE: [res.DISEASE_SYNS]})
    abbrev_synonyms: dict = field(default_factory=lambda: {HitType.DISEASE: [res.DISEASE_ABBREV]})
    output_dir: Path = output_path(OUTPUTS_DIR / "disease")
    abbrev_mode: str | None = 'relaxed'
    no_abbrev_syn_list: list = field(default_factory=lambda: [res.DISEASE_ABBREV])
    word_char: str = "SYNONYMS"
    disease_obo_path: Path = res.MONDO_OBO


@dataclass
class ExistingSyngrepDiseaseConfig(ValidatedConfig):
    output_name: str
    hits_path: Path
    synfile_map_path: Path
    synfile_type_map_path: Path
    output_dir: Path = output_path(OUTPUTS_DIR / "disease")
    disease_obo_path: Path = res.MONDO_OBO

    
@dataclass
class MirbaseResources:
    """Bundle of miRBase-derived mapping/normalization files, shared by every
    config that needs miRNA resolution."""
    families_path: Path = res.MIR_FAMILY_PATH
    precursor_path: Path = res.MIR_PRECURSOR_PATH
    mature_path: Path = res.MIR_MATURE_PATH
    parent_to_child_path: Path = res.MIR_PARENT_TO_CHILD_PATH
    mirna_taxons_path: Path = res.MIR_TAXONS_PATH
    mirna_to_prefix_path: Path = res.MIR_TO_PREFIX_PATH
    family_norm_path: Path = res.MIR_FAMILY_NORM_PATH
    precursor_norm_path: Path = res.MIR_PRECURSOR_NORM_PATH
    mature_norm_path: Path = res.MIR_MATURE_NORM_PATH
    precursor_ambi_path: Path = res.MIR_PRECURSOR_AMBI_PATH
    mature_ambi_path: Path = res.MIR_MATURE_AMBI_PATH


@dataclass
class MirnaPipelineConfig(ValidatedConfig):
    output_name: str
    n_tasks: int = 50
    sentence_pattern: str = str(res.CORPUS_DIR / "*.sent")
    synonyms: dict = field(default_factory=lambda: {
        HitType.MIR: [res.MIR_SYNS],
        HitType.TAXON: [res.SPECIES_SYNS, res.SPECIES_FROM_CL_SYNS],
    })
    output_dir: Path = output_path(OUTPUTS_DIR / "mirna")
    abbrev_mode: str = 'relaxed'
    no_abbrev_syn_list: list = field(default_factory=lambda: [res.MIR_SYNS])
    within_word: list = field(default_factory=lambda: [res.MIR_SYNS.name])
    sentence_path: Path = res.SENTENCES_SORTED
    mirbase: MirbaseResources = field(default_factory=MirbaseResources)
    taxon_obo_path: Path = res.TAXON_OBO


@dataclass
class ExistingSyngrepMirnaConfig(ValidatedConfig):
    output_name: str
    hits_path: Path
    synfile_map_path: Path
    synfile_type_map_path: Path
    synonyms: dict = field(default_factory=lambda: {
        HitType.MIR: [res.MIR_SYNS],
        HitType.TAXON: [res.SPECIES_SYNS, res.SPECIES_FROM_CL_SYNS],
    })
    output_dir: Path = output_path(OUTPUTS_DIR / "mirna")
    sentence_path: Path = res.SENTENCES_SORTED
    mirbase: MirbaseResources = field(default_factory=MirbaseResources)
    taxon_obo_path: Path = res.TAXON_OBO


@dataclass
class CompleteConfig(ValidatedConfig):
    output_name: str
    n_tasks: int = 50
    sentence_pattern: str = str(res.CORPUS_DIR / "*.sent")
    output_dir: Path = output_path(OUTPUTS_DIR / "complete_run")
    sentence_path: Path = res.SENTENCES_SORTED
    mirbase: MirbaseResources = field(default_factory=MirbaseResources)
    synonyms: dict = field(default_factory=lambda: {HitType.DISEASE: [res.DISEASE_SYNS],
                                                    HitType.MIR: [res.MIR_SYNS],
                                                    HitType.TAXON: [res.SPECIES_SYNS, res.SPECIES_FROM_CL_SYNS],
                                                    HitType.CELL: [res.CELL_SYNS],
                                                    HitType.TISSUE: [res.TISSUE_SYNS],
                                                    HitType.PATHWAY: [res.PATHWAY_SYNS],
                                                    HitType.BIOLOGICAL_PROCESS: [res.BIOLOGICAL_PROCESS_SYNS]})
    abbrev_synonyms: dict = field(default_factory=lambda: {HitType.DISEASE: [res.DISEASE_ABBREV]})
    abbrev_mode: str | None = 'relaxed'
    no_abbrev_syn_list: list = field(default_factory=lambda: [res.DISEASE_ABBREV, res.MIR_SYNS])
    within_word: list = field(default_factory=lambda: [res.MIR_SYNS.name])
    taxon_obo_path: Path = res.TAXON_OBO
    disease_obo_path: Path = res.MONDO_OBO
    cell_obo_path: Path = res.CELL_OBO
    tissue_obo_path: Path = res.TISSUE_OBO
    pathway_obo_path: Path = res.PATHWAY_OBO
    bp_obo_path: Path = res.GO_OBO


@dataclass
class ExistingSyngrepCompleteConfig(ValidatedConfig):
    output_name: str
    hits_path: Path
    synfile_map_path: Path
    synfile_type_map_path: Path
    output_dir: Path = output_path(OUTPUTS_DIR / "complete_run")
    sentence_path: Path = res.SENTENCES_SORTED
    mirbase: MirbaseResources = field(default_factory=MirbaseResources)
    taxon_obo_path: Path = res.TAXON_OBO
    disease_obo_path: Path = res.MONDO_OBO
    cell_obo_path: Path = res.CELL_OBO
    tissue_obo_path: Path = res.TISSUE_OBO
    pathway_obo_path: Path = res.PATHWAY_OBO
    bp_obo_path: Path = res.GO_OBO
