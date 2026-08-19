import dataclasses
from pathlib import Path



## CORPUS
CORPUS_DIR = Path("/mnt/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/corpus")
SENTENCES_SORTED = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/corpus/original/everything_sorted.sent")
CORPUS_SAMPLE = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/corpus/samples/sample_1.sent")
CORPUS_SAMPLE_SMALLER = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/corpus/samples/chunk_1.txt")

## ONTOLOGY
ONTOLOGIES_DIR = Path("/mnt/raidbio2/extstud/studtemp/mitsopoulos/ontologies")
MONDO_OBO = Path("/mnt/raidbio2/extstud/studtemp/mitsopoulos/ontologies/diseases/mondo_disease_ontology.obo")
TAXON_OBO = Path("/mnt/raidbio2/extstud/studtemp/mitsopoulos/ontologies/taxonomy/ncbi_taxonomy.obo")
CELL_OBO = Path("/mnt/raidbio2/extstud/studtemp/mitsopoulos/ontologies/cell/cell_ontology_base.obo")
TISSUE_OBO = Path("/mnt/raidbio2/extstud/studtemp/mitsopoulos/ontologies/cell/brenda_tissue_ontology.obo")
PATHWAY_OBO = Path("/mnt/raidbio2/extstud/studtemp/mitsopoulos/ontologies/pathways/pathway_ontology.obo")
GO_OBO = Path("/mnt/raidbio2/extstud/studtemp/mitsopoulos/ontologies/pathways/gene_ontology.obo")

## SYNONYM
TISSUE_SYNS = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/bto.syn")
CELL_SYNS = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/cl.syn")
DISEASE_ABBREV = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/disease_abbreviations.syn")
DISEASE_SYNS = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/disease.syn")
SPECIES_SYNS = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/linnaeus_species.syn")
SPECIES_FROM_CL_SYNS = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/linnaeus_cell_lines.syn")
MIR_SYNS = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/mir_regex.syn")
PATHWAY_SYNS = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/pw.syn")
BIOLOGICAL_PROCESS_SYNS = Path("/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/go.syn")

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
