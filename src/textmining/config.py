from dataclasses import dataclass, field
from pathlib import Path
import textmining.resources as res
from textmining.mirbase import load_mirbase
from textmining.types import HitType
from textmining.ontology import OntologyGraph
from textmining.normalization import MirNormalizer, DefaultNormalizer
from textmining.normalization_resources import MirResourceLoader
from textmining.sentence_utils import SentenceReader
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
class RuntimeResources:
    """Constructed, pipeline-owned resources shared across entity configs at
    normalizer-build time. Normally built automatically from
    BasePipelineConfig.sentence_path in __post_init__, so entity configs and
    the sentence reader always agree on which corpus is in play; pass an
    explicit instance only to override that derived default.

    sentence_reader is opened lazily on first access, so a pipeline that
    never constructs a normalizer needing it never opens the corpus file.
    """
    sentence_path: Path | None = None
    _sentence_reader: SentenceReader | None = field(default=None, init=False, repr=False)

    @property
    def sentence_reader(self) -> SentenceReader:
        if self.sentence_path is None:
            raise ValueError("RuntimeResources has no sentence_path configured")
        if self._sentence_reader is None:
            self._sentence_reader = SentenceReader(self.sentence_path)
        return self._sentence_reader

    def close(self):
        if self._sentence_reader is not None:
            self._sentence_reader.close()
            self._sentence_reader = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


@dataclass
class EntityConfig():
    entity_type: HitType
    synonyms: list[Path]
    no_abbrev: list[Path] = field(default_factory=list)
    within_word: list[Path] = field(default_factory=list)
    abbrev_synonyms: list[Path] = field(default_factory=list)

    def get_graph(self):
        source = res.ONTOLOGY_SOURCES.get(self.entity_type)
        if not source:
            raise ValueError(f'No ontology source stored for entity type: {self.entity_type}')
        if source.cache_path and source.cache_path.exists():
            return OntologyGraph.load(source.cache_path)
        else:
            return OntologyGraph.from_obo(
                obo_path=source.local_path,
                **source.obo_kwargs
            )

    def get_normalizer(self, resources: RuntimeResources) -> DefaultNormalizer:
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

    def get_graph(self):
        return OntologyGraph.from_dict(
            *load_mirbase(families_tsv=self.mirbase.families_path,
                          precursors_tsv=self.mirbase.precursor_path,
                          mature_tsv=self.mirbase.mature_path,
                          parent_to_child_tsv=self.mirbase.parent_to_child_path)
            )

    def get_normalizer(self, resources: RuntimeResources) -> MirNormalizer:
        norm_resources = MirResourceLoader.load(
            mirna_taxons_path=self.mirbase.mirna_taxons_path,
            mirna_2_prefix_path=self.mirbase.mirna_to_prefix_path,
            family_normalizer_path=self.mirbase.family_norm_path,
            precursor_normalizer_path=self.mirbase.precursor_norm_path,
            mature_normalizer_path=self.mirbase.mature_norm_path,
            precursor_ambiguous_path=self.mirbase.precursor_ambi_path,
            mature_ambiguous_path=self.mirbase.mature_ambi_path,
        )
        return MirNormalizer(resources.sentence_reader, norm_resources)

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


@dataclass(kw_only=True)
class BasePipelineConfig(ValidatedConfig):
    output_name: str
    output_dir: Path = field(metadata={"skip_validation": True})
    entity_configs: list[EntityConfig]
    sentence_path: Path = res.SENTENCES_SORTED
    runtime_resources: RuntimeResources | None = None

    def __post_init__(self) -> None:
        if self.runtime_resources is None:
            self.runtime_resources = RuntimeResources(self.sentence_path)
        super().__post_init__()

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
class MirnaExistingSyngrepPipelineConfig(ExistingSyngrepPipelineConfig):
    entity_configs: list[EntityConfig] = field(default_factory=lambda:[MirConfig(), TaxonConfig()])
