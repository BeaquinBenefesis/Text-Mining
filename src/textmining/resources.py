import dataclasses
from pathlib import Path
from dataclasses import dataclass, field
from textmining.models import HitType
from textmining import external
from textmining.synonym_utils import ExtractedSynonymSpec

## CORPUS
CORPUS_DIR = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/corpus/filtered_corpus")
CORPUS_SAMPLE = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/corpus/filtered_corpus/chunk_1.sent")
CORPUS_SAMPLE_SMALLER = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/corpus/filtered_corpus/samples/chunk_1.sent")

## ONTOLOGY
ONTOLOGIES_DIR = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/ontologies")
MONDO_OBO = ONTOLOGIES_DIR / "mondo_disease_ontology.obo"
TAXON_OBO = ONTOLOGIES_DIR / "ncbi_taxonomy.obo"
CELL_OBO = ONTOLOGIES_DIR / "cell_ontology_base.obo"
TISSUE_OBO = ONTOLOGIES_DIR / "brenda_tissue_ontology.obo"
PATHWAY_OBO = ONTOLOGIES_DIR / "pathway_ontology.obo"
GO_OBO = ONTOLOGIES_DIR / "gene_ontology.obo"

@dataclass(frozen=True)
class OntologySource:
    hit_type: HitType
    local_path: Path
    url: str | None
    cache_path: Path
    obo_kwargs: dict = field(default_factory=dict)
    source: str = ""   # short canonical label for entity.source, e.g. 'mondo', 'go'
    roots: tuple[str, ...] | None = None   # graph is restricted to these + descendants. None = whole file

ONTOLOGY_ROOTS: dict[HitType, tuple[str, ...]] = {
    HitType.DISEASE: ('MONDO:0000001',),
    HitType.TAXON: ('NCBITaxon:131567', 'NCBITaxon:10239'),
    HitType.CELL: ('CL:0000000',),
    HitType.TISSUE: ('BTO:0000042', 'BTO:0001494', 'BTO:0001490', 'BTO:0001481'),
    HitType.PATHWAY: ('PW:0000001',),
    HitType.BIOLOGICAL_PROCESS: ('GO:0008150',),
}

ONTOLOGY_SOURCES: dict[HitType, OntologySource] = {
    HitType.DISEASE: OntologySource(HitType.DISEASE,
                                    MONDO_OBO,
                                    url=external.MONDO_OBO_URL,
                                    cache_path=MONDO_OBO.with_suffix('.pkl'),
                                    obo_kwargs={'exclude_gci': True},
                                    source='mondo',
                                    roots=ONTOLOGY_ROOTS[HitType.DISEASE]),
    HitType.TAXON:   OntologySource(HitType.TAXON,
                                    TAXON_OBO,
                                    url=external.TAXON_OBO_URL,
                                    cache_path=TAXON_OBO.with_suffix('.pkl'),
                                    source='ncbi_taxonomy'),
                                    # NOT restricted: 20,598 ids in the LINNAEUS .syn files lie
                                    # outside ONTOLOGY_ROOTS[TAXON] and would stop resolving.
    HitType.CELL:    OntologySource(HitType.CELL, CELL_OBO, url=external.CL_OBO_URL, cache_path=CELL_OBO.with_suffix('.pkl'), source='cl', roots=ONTOLOGY_ROOTS[HitType.CELL]),
    HitType.TISSUE:  OntologySource(HitType.TISSUE, TISSUE_OBO, url=external.BTO_OBO_URL, cache_path=TISSUE_OBO.with_suffix('.pkl'), source='bto', roots=ONTOLOGY_ROOTS[HitType.TISSUE]),
    HitType.PATHWAY: OntologySource(HitType.PATHWAY, PATHWAY_OBO, url=external.PW_OBO_URL, cache_path=PATHWAY_OBO.with_suffix('.pkl'), source='pw', roots=ONTOLOGY_ROOTS[HitType.PATHWAY]),
    HitType.BIOLOGICAL_PROCESS: OntologySource(HitType.BIOLOGICAL_PROCESS, GO_OBO, url=external.GO_OBO_URL, cache_path=GO_OBO.with_suffix('.pkl'), source='go', roots=ONTOLOGY_ROOTS[HitType.BIOLOGICAL_PROCESS]),
}


## SYNONYM
SYNONYM_DIR = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final")
TISSUE_SYNS = SYNONYM_DIR / "bto.syn"
TISSUE_ABBREV = SYNONYM_DIR / "tissue_abbreviations.syn"
CELL_SYNS = SYNONYM_DIR / "cl.syn"
CELL_ABBREV = SYNONYM_DIR / "cell_abbreviations.syn"
DISEASE_ABBREV = SYNONYM_DIR / "disease_abbreviations.syn"
DISEASE_SYNS = SYNONYM_DIR / "disease.syn"
SPECIES_SYNS = SYNONYM_DIR / "linnaeus_species.syn"
SPECIES_FROM_CL_SYNS = SYNONYM_DIR / "linnaeus_cell_lines.syn"
MIR_SYNS = SYNONYM_DIR / "mir_regex.syn"
PATHWAY_SYNS = SYNONYM_DIR / "pw.syn"
PATHWAY_ABBREV = SYNONYM_DIR / "pathway_abbreviations.syn"
BIOLOGICAL_PROCESS_SYNS = SYNONYM_DIR / "go.syn"
BIOLOGICAL_PROCESS_ABBREV = SYNONYM_DIR / "biological_process_abbreviations.syn"


EXTRACTABLE_SYNONYMS: dict[HitType, list[ExtractedSynonymSpec]] = {
    HitType.DISEASE:  [ExtractedSynonymSpec(output_path=DISEASE_SYNS, abbreviation_output_path=DISEASE_ABBREV, roots=ONTOLOGY_ROOTS[HitType.DISEASE])],
    HitType.CELL:     [ExtractedSynonymSpec(output_path=CELL_SYNS, abbreviation_output_path=CELL_ABBREV, roots=ONTOLOGY_ROOTS[HitType.CELL])],
    HitType.TISSUE:   [ExtractedSynonymSpec(TISSUE_SYNS, abbreviation_output_path=TISSUE_ABBREV, roots=ONTOLOGY_ROOTS[HitType.TISSUE])],
    HitType.PATHWAY:  [ExtractedSynonymSpec(PATHWAY_SYNS, abbreviation_output_path=PATHWAY_ABBREV, roots=ONTOLOGY_ROOTS[HitType.PATHWAY])],
    HitType.BIOLOGICAL_PROCESS: [ExtractedSynonymSpec(BIOLOGICAL_PROCESS_SYNS, abbreviation_output_path=BIOLOGICAL_PROCESS_ABBREV, roots=ONTOLOGY_ROOTS[HitType.BIOLOGICAL_PROCESS])],
}


## MIRNA DATA
MIR_FAMILY_PATH = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/mappings/families.tsv")
MIR_PRECURSOR_PATH = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/mappings/precursors.tsv")
MIR_MATURE_PATH = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/mappings/mature.tsv")
MIR_PARENT_TO_CHILD_PATH = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/mappings/parent_to_child.tsv")
MIR_TAXONS_PATH = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/mirna_taxons.tsv")
MIR_TO_PREFIX_PATH = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/mirna_prefix_mapping.json")
MIR_FAMILY_NORM_PATH = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/family_normalization_dict.json")
MIR_PRECURSOR_NORM_PATH = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/precursor_normalization_dict.json")
MIR_MATURE_NORM_PATH = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/mature_normalization_dict.json")
MIR_PRECURSOR_AMBI_PATH = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/precursor_id_conflicts.tsv")
MIR_MATURE_AMBI_PATH = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/mature_id_conflicts.tsv")
# Full per-release name<->accession record. Superset of the *_id_conflicts files:
# the conflicted names are exactly `GROUP BY mirna_name HAVING COUNT(DISTINCT
# accession) > 1` over these (verified set-identical after casefolding).
MIR_MATURE_HISTORY_PATH = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/mirna_mature_history.tsv")
MIR_PRECURSOR_HISTORY_PATH = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/mirna_precursor_history.tsv")
MIR_TEST_SENTS = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/testing/mirbase.sent")

## VALIDATION
HMDD_SENTS = Path("/mnt/raidbio2/extstud/studtemp/mitsopoulos/HMDD/associations.sent")

def validate_resource(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"{path} not found!")

def validate_paths(value):
    """Recursively validate_resource() every Path found in value, walking
    into dicts/lists/tuples/sets and nested dataclasses. Non-Path leaves
    (str, int, bool, None, ...) are silently skipped."""
    if value is None:
        return
    if isinstance(value, Path):
        validate_resource(value)
    elif isinstance(value, dict):
        for v in value.values():
            validate_paths(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            validate_paths(v)
    elif dataclasses.is_dataclass(value):
        for f in dataclasses.fields(value):
            if f.metadata.get("skip_validation"):
                continue
            validate_paths(getattr(value, f.name))



## METADATA
PUBMED_METADATA = Path("/mnt/raidbio2/extdata/textmining/master/pubmed_metadata.csv")
PMC_METADATA = Path("/mnt/raidbio2/extdata/textmining/master/pmc_metadata.csv")
