from textmining.config import CompleteConfig, ExistingSyngrepCompleteConfig, MirbaseResources
from textmining.syngrep import run_syngrep
from textmining.hit_utils import HitProcessor
from textmining.ontology import OntologyGraph
from textmining.models import HitType
from textmining.normalization import MirNormalizer, DefaultNormalizer
from textmining.scoring import HitScorer
from textmining.core import Processor
from textmining.results_io import write_normalized_hits_tsv
from textmining.progress import track_progress
from textmining.mirbase import load_mirbase
from textmining.sentence_utils import SentenceReader
from textmining.normalization_resources import MirResourceLoader
from textmining.logging_utils import setup_logging

def process_hits(
    sentence_path,
    hits_path,
    synfile_map_path,
    synfile_type_map_path,
    mirbase_resources: MirbaseResources,
    taxon_obo_path,
    disease_obo_path,
    cell_obo_path,
    tissue_obo_path,
    pathway_obo_path,
    bp_obo_path,
    output_path,
):
    sentence_reader = SentenceReader(sentence_path=sentence_path)
    
    mirna_resources = MirResourceLoader.load(
        mirna_taxons_path=mirbase_resources.mirna_taxons_path,
        mirna_2_prefix_path=mirbase_resources.mirna_to_prefix_path,
        family_normalizer_path=mirbase_resources.family_norm_path,
        precursor_normalizer_path=mirbase_resources.precursor_norm_path,
        mature_normalizer_path=mirbase_resources.mature_norm_path,
        precursor_ambiguous_path=mirbase_resources.precursor_ambi_path,
        mature_ambiguous_path=mirbase_resources.mature_ambi_path
    )
    
    mirna_graph = OntologyGraph.from_dict(*load_mirbase(families_tsv=mirbase_resources.families_path,
                                                       precursors_tsv=mirbase_resources.precursor_path,
                                                       mature_tsv=mirbase_resources.mature_path,
                                                       parent_to_child_tsv=mirbase_resources.parent_to_child_path))
    taxon_graph = OntologyGraph.from_obo(taxon_obo_path)
    disease_graph = OntologyGraph.from_obo(disease_obo_path, exclude_gci=True)
    cell_graph = OntologyGraph.from_obo(cell_obo_path)
    tissue_graph = OntologyGraph.from_obo(tissue_obo_path)
    pathway_graph = OntologyGraph.from_obo(pathway_obo_path)
    bp_graph = OntologyGraph.from_obo(bp_obo_path)
    
    type_to_ontology = {HitType.MIR: mirna_graph,
                        HitType.TAXON: taxon_graph,
                        HitType.DISEASE: disease_graph,
                        HitType.CELL: cell_graph,
                        HitType.TISSUE: tissue_graph,
                        HitType.PATHWAY: pathway_graph,
                        HitType.BIOLOGICAL_PROCESS: bp_graph}
    
    hits_processor = HitProcessor(hits_path=hits_path, 
                                  synfile_map=synfile_map_path, 
                                  synfile_type_map=synfile_type_map_path,
                                  type_to_ontology=type_to_ontology)
    mir_normalizer = MirNormalizer(sentence_reader=sentence_reader,
                                       resources=mirna_resources)
    default_normalizer = DefaultNormalizer()
    normalizers = {
        HitType.MIR: mir_normalizer,
        HitType.TAXON: default_normalizer,
        HitType.DISEASE: default_normalizer,
        HitType.CELL: default_normalizer,
        HitType.TISSUE: default_normalizer,
        HitType.PATHWAY: default_normalizer,
        HitType.BIOLOGICAL_PROCESS: default_normalizer
    }
    scorer = HitScorer(type_to_ontology=type_to_ontology)
    
    main_processor = Processor(hits_processor=hits_processor,
                               normalizers=normalizers,
                               scorer=scorer)
    article_stream = track_progress(main_processor.get_normalized_article_stream(), label='articles', report_every=1000)
    write_normalized_hits_tsv(article_stream,
                              output_path)

def run_complete_pipeline(output_name: str, sentence_path = None):
    config = CompleteConfig(output_name)
    
    if sentence_path:
        config.sentence_pattern = sentence_path
        config.sentence_path = sentence_path
        
    setup_logging(output_dir=config.output_dir,
                  run_name=output_name)
    
    res = run_syngrep(
        sentence_pattern=config.sentence_pattern,
        synonyms=config.synonyms,
        output_dir=config.output_dir,
        within_word=config.within_word,
        output_name=config.output_name,
        abbrev=config.abbrev,
        ntasks=config.n_tasks,
    )
    
    process_hits(
        sentence_path=config.sentence_path,
        hits_path=res.hits_path,
        synfile_map_path=res.synfile_map_path,
        synfile_type_map_path=res.synfile_type_map_path,
        mirbase_resources=config.mirbase,
        taxon_obo_path=config.taxon_obo_path,
        disease_obo_path=config.disease_obo_path,
        cell_obo_path=config.cell_obo_path,
        tissue_obo_path=config.tissue_obo_path,
        pathway_obo_path=config.pathway_obo_path,
        bp_obo_path=config.bp_obo_path,
        output_path=config.output_dir / f"{config.output_name}.norm"
    )

def run_existing_syngrep_complete_pipeline(config: ExistingSyngrepCompleteConfig):
    setup_logging(output_dir=config.output_dir,
                  run_name=config.output_name)
    process_hits(
        sentence_path=config.sentence_path,
        hits_path=config.hits_path,
        synfile_map_path=config.synfile_map_path,
        synfile_type_map_path=config.synfile_type_map_path,
        mirbase_resources=config.mirbase,
        taxon_obo_path=config.taxon_obo_path,
        disease_obo_path=config.disease_obo_path,
        cell_obo_path=config.cell_obo_path,
        tissue_obo_path=config.tissue_obo_path,
        pathway_obo_path=config.pathway_obo_path,
        bp_obo_path=config.bp_obo_path,
        output_path=config.output_dir / f"{config.output_name}.norm"
    )

