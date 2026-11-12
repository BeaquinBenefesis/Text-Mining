import json
from dataclasses import dataclass, field
from pathlib import Path
import textmining.resources as res
from textmining.mirbase import load_mirbase
from textmining.enums import HitType
from textmining.ontology import OntologyGraph
from textmining.hit_utils import GroupResolver, LcaResolver, GeneResolver
from textmining.normalization import MirNormalizer, DefaultNormalizer
from textmining.normalization_resources import MirResourceLoader
from textmining.syngrep import SynGrepResult

class ValidatedConfig:

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        res.validate_paths(self)


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
class EntityConfig():
    entity_type: HitType
    synonyms: list[Path]
    no_abbrev: list[Path] = field(default_factory=list)
    within_word: list[Path] = field(default_factory=list)
    abbrev_synonyms: list[Path] = field(default_factory=list)

    def get_graph(self) -> OntologyGraph | None:
        source = res.ONTOLOGY_SOURCES.get(self.entity_type)
        if not source:
            raise ValueError(f'No ontology source stored for entity type: {self.entity_type}')
        return OntologyGraph.from_source(source)

    # Chooses among several ids of this type at one span. graph is the result of get_graph()
    def get_resolver(self, graph: OntologyGraph | None) -> GroupResolver | None:
        return LcaResolver(graph) if graph is not None else None

    def get_normalizer(self) -> DefaultNormalizer:
        return DefaultNormalizer()

@dataclass
class DiseaseConfig(EntityConfig):
    entity_type: HitType = HitType.DISEASE
    synonyms: list[Path] = field(default_factory=lambda:[res.DISEASE_SYNS])
    abbrev_synonyms: list[Path] = field(default_factory=lambda:[res.DISEASE_ABBREV])
    no_abbrev: list[Path] = field(default_factory=lambda:[res.DISEASE_ABBREV])


@dataclass
class MirConfig(EntityConfig):
    entity_type: HitType = HitType.MIR
    synonyms: list[Path] = field(default_factory=lambda:[res.MIR_SYNS])
    no_abbrev: list[Path] = field(default_factory=lambda:[res.MIR_SYNS])
    mirbase: MirbaseResources = field(default_factory=MirbaseResources)
    within_word: list[Path] = field(default_factory=lambda:[res.MIR_SYNS])

    def get_graph(self):
        return OntologyGraph.from_dict(
            *load_mirbase(families_tsv=self.mirbase.families_path,
                          precursors_tsv=self.mirbase.precursor_path,
                          mature_tsv=self.mirbase.mature_path,
                          parent_to_child_tsv=self.mirbase.parent_to_child_path)
            )

    def get_normalizer(self) -> MirNormalizer:
        norm_resources = MirResourceLoader.load(
            mirna_taxons_path=self.mirbase.mirna_taxons_path,
            mirna_2_prefix_path=self.mirbase.mirna_to_prefix_path,
            family_normalizer_path=self.mirbase.family_norm_path,
            precursor_normalizer_path=self.mirbase.precursor_norm_path,
            mature_normalizer_path=self.mirbase.mature_norm_path,
            precursor_ambiguous_path=self.mirbase.precursor_ambi_path,
            mature_ambiguous_path=self.mirbase.mature_ambi_path,
            parent_to_child_path=self.mirbase.parent_to_child_path,
        )
        return MirNormalizer(norm_resources)

    # miRNA ids are regex tokens, not graph ids. They are settled by the normalizer
    def get_resolver(self, graph=None):
        return None

@dataclass
class TaxonConfig(EntityConfig):
    entity_type: HitType = HitType.TAXON
    synonyms: list[Path] = field(default_factory=lambda:[res.SPECIES_SYNS, res.SPECIES_FROM_CL_SYNS])


@dataclass
class TissueConfig(EntityConfig):
    entity_type: HitType = HitType.TISSUE
    synonyms: list[Path] = field(default_factory=lambda:[res.TISSUE_SYNS])
    abbrev_synonyms: list[Path] = field(default_factory=lambda:[res.TISSUE_ABBREV])
    no_abbrev: list[Path] = field(default_factory=lambda:[res.TISSUE_ABBREV])


@dataclass
class CellConfig(EntityConfig):
    entity_type: HitType =  HitType.CELL
    synonyms: list[Path] = field(default_factory=lambda:[res.CELL_SYNS])
    abbrev_synonyms: list[Path] = field(default_factory=lambda:[res.CELL_ABBREV])
    no_abbrev: list[Path] = field(default_factory=lambda:[res.CELL_ABBREV])

@dataclass
class PathwayConfig(EntityConfig):
    entity_type: HitType =  HitType.PATHWAY
    synonyms: list[Path] = field(default_factory=lambda:[res.PATHWAY_SYNS])
    abbrev_synonyms: list[Path] = field(default_factory=lambda:[res.PATHWAY_ABBREV])
    no_abbrev: list[Path] = field(default_factory=lambda:[res.PATHWAY_ABBREV])


@dataclass
class BpConfig(EntityConfig):
    entity_type: HitType =  HitType.BIOLOGICAL_PROCESS
    synonyms: list[Path] = field(default_factory=lambda:[res.BIOLOGICAL_PROCESS_SYNS])
    abbrev_synonyms: list[Path] = field(default_factory=lambda:[res.BIOLOGICAL_PROCESS_ABBREV])
    no_abbrev: list[Path] = field(default_factory=lambda:[res.BIOLOGICAL_PROCESS_ABBREV])

@dataclass
class GeneConfig(EntityConfig):
    entity_type: HitType = HitType.GENE
    synonyms: list[Path] = field(default_factory=lambda:[res.GENE_SYNS])
    taxon_map: Path = res.GENE_TAXON_MAP
    # organism assumed when none of a gene name's organisms is mentioned in the article.
    # None leaves such names unresolved
    default_taxon: str | None = None

    def get_graph(self):
        return None

    def get_resolver(self, graph=None) -> GeneResolver:
        with open(self.taxon_map) as f:
            gene_to_taxon = json.load(f)
        return GeneResolver(gene_to_taxon, default_taxon=self.default_taxon)


@dataclass(kw_only=True)
class BasePipelineConfig(ValidatedConfig):
    output_name: str
    output_dir: Path = field(metadata={"skip_validation": True})
    entity_configs: list[EntityConfig]
    sentence_pattern: str = str(res.CORPUS_DIR / "*.sent")

@dataclass(kw_only=True)
class SyngrepInputs:
    sentence_pattern: str = str(res.CORPUS_DIR / "*.sent")
    n_tasks: int = 50
    word_char: str = 'SYNONYMS'
    abbrev_mode: str | None = 'relaxed'

@dataclass(kw_only=True)
class PipelineConfig(SyngrepInputs, BasePipelineConfig):
    ...
    
    @property
    def synonym_paths(self) -> dict[HitType, list[Path]]:
        return {
            e.entity_type: e.synonyms for e in self.entity_configs
        }
    
    @property
    def abbrev_paths(self) -> dict[HitType, list[Path]]:
        return {
            e.entity_type: e.abbrev_synonyms for e in self.entity_configs if e.abbrev_synonyms
        }
    
    @property
    def within_word(self) -> list[Path]:
        return [p for e in self.entity_configs for p in e.within_word]
    
    @property
    def no_abbrev_file_names(self) -> list[Path]:
        return [p for e in self.entity_configs for p in e.no_abbrev]

@dataclass(kw_only=True)
class ExistingSyngrepPipelineConfig(BasePipelineConfig):
    syngrep_result: SynGrepResult


@dataclass(kw_only=True)
class MirnaPipelineConfig(PipelineConfig):
    entity_configs: list[EntityConfig] = field(default_factory=lambda:[MirConfig(), TaxonConfig()])

@dataclass(kw_only=True)
class DiseasePipelineConfig(PipelineConfig):
    entity_configs: list[EntityConfig] = field(default_factory=lambda:[DiseaseConfig()])

@dataclass(kw_only=True)
class CompletePipelineConfig(PipelineConfig):
    entity_configs: list[EntityConfig] = field(default_factory=lambda:[MirConfig(), 
                                                                      TaxonConfig(), 
                                                                      DiseaseConfig(), 
                                                                      TissueConfig(),
                                                                      CellConfig(),
                                                                      PathwayConfig(),
                                                                      BpConfig(),
                                                                      GeneConfig()])

@dataclass(kw_only=True)
class MirnaDiseasePipelineConfig(PipelineConfig):
    entity_configs: list[EntityConfig] = field(default_factory=lambda:[MirConfig(), TaxonConfig(), DiseaseConfig()])
    
@dataclass(kw_only=True)
class MirnaGenePipelineConfig(PipelineConfig):
    entity_configs: list[EntityConfig] = field(default_factory=lambda:[MirConfig(), TaxonConfig(), GeneConfig()])

@dataclass(kw_only=True)
class MirnaExistingSyngrepPipelineConfig(ExistingSyngrepPipelineConfig):
    entity_configs: list[EntityConfig] = field(default_factory=lambda:[MirConfig(), TaxonConfig()])
