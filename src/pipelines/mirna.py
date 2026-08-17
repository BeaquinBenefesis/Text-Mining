from textmining.config import MirnaPipelineConfig, ExistingSyngrepMirnaConfig
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

def process_mirna_hits(
    sentence_path,
    hits_path,
    synfile_map_path,
    synfile_type_map_path,
    families_path,
    precursors_path,
    mature_path,
    parent_to_child_path,
    mirna_taxons_path,
    mirna_2_prefix_path,
    family_normalizer_path,
    precursor_normalizer_path,
    mature_normalizer_path,
    taxon_obo_path,
    precursor_ambiguous_path,
    mature_ambiguous_path,
    output_path,
):
    sentence_reader = SentenceReader(sentence_path=sentence_path)
    resources = MirResourceLoader.load(
        mirna_taxons_path=mirna_taxons_path,
        mirna_2_prefix_path=mirna_2_prefix_path,
        family_normalizer_path=family_normalizer_path,
        precursor_normalizer_path=precursor_normalizer_path,
        mature_normalizer_path=mature_normalizer_path,
        precursor_ambiguous_path=precursor_ambiguous_path,
        mature_ambiguous_path=mature_ambiguous_path
    )
    mirna_graph = OntologyGraph.from_dict(*load_mirbase(families_tsv=families_path,
                                                       precursors_tsv=precursors_path,
                                                       mature_tsv=mature_path,
                                                       parent_to_child_tsv=parent_to_child_path))
    #relevant_taxons_internal = {to_internal_id(t) for t in resources.relevant_taxons}
    taxon_graph = OntologyGraph.from_obo(taxon_obo_path)
    type_to_ontology = {HitType.MIR: mirna_graph,
                        HitType.TAXON: taxon_graph}
    hits_processor = HitProcessor(hits_path=hits_path, 
                                  synfile_map=synfile_map_path, 
                                  synfile_type_map=synfile_type_map_path,
                                  type_to_ontology=type_to_ontology)
    mir_normalizer = MirNormalizer(sentence_reader=sentence_reader,
                                       resources=resources)
    default_normalizer = DefaultNormalizer()
    normalizers = {
        HitType.MIR: mir_normalizer,
        HitType.TAXON: default_normalizer
    }
    scorer = HitScorer(type_to_ontology=type_to_ontology)
    
    main_processor = Processor(hits_processor=hits_processor,
                               normalizers=normalizers,
                               scorer=scorer)
    article_stream = track_progress(main_processor.get_normalized_article_stream(), label='articles', report_every=1000)
    write_normalized_hits_tsv(article_stream,
                              output_path)

def run_mirna_pipeline(output_name: str, sentence_path = None):
    config = MirnaPipelineConfig(output_name)
    if sentence_path:
        config.sentence_pattern = sentence_path
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
    process_mirna_hits(
        sentence_path=config.sentence_path,
        hits_path=res.hits_path,
        synfile_map_path=res.synfile_map_path,
        synfile_type_map_path=res.synfile_type_map_path,
        families_path=config.mirbase.families_path,
        precursors_path=config.mirbase.precursor_path,
        mature_path=config.mirbase.mature_path,
        parent_to_child_path=config.mirbase.parent_to_child_path,
        mirna_taxons_path=config.mirbase.mirna_taxons_path,
        mirna_2_prefix_path=config.mirbase.mirna_to_prefix_path,
        family_normalizer_path=config.mirbase.family_norm_path,
        precursor_normalizer_path=config.mirbase.precursor_norm_path,
        mature_normalizer_path=config.mirbase.mature_norm_path,
        precursor_ambiguous_path=config.mirbase.precursor_ambi_path,
        mature_ambiguous_path=config.mirbase.mature_ambi_path,
        taxon_obo_path=config.taxon_obo_path,
        output_path=config.output_dir / f"{config.output_name}.norm"

    )

def run_existing_mirna_pipeline(config: ExistingSyngrepMirnaConfig):
        setup_logging(output_dir=config.output_dir,
                      run_name=config.output_name)
        process_mirna_hits(
        sentence_path=config.sentence_path,
        hits_path=config.hits_path,
        synfile_map_path=config.synfile_map_path,
        synfile_type_map_path=config.synfile_type_map_path,
        families_path=config.mirbase.families_path,
        precursors_path=config.mirbase.precursor_path,
        mature_path=config.mirbase.mature_path,
        parent_to_child_path=config.mirbase.parent_to_child_path,
        mirna_taxons_path=config.mirbase.mirna_taxons_path,
        mirna_2_prefix_path=config.mirbase.mirna_to_prefix_path,
        family_normalizer_path=config.mirbase.family_norm_path,
        precursor_normalizer_path=config.mirbase.precursor_norm_path,
        mature_normalizer_path=config.mirbase.mature_norm_path,
        precursor_ambiguous_path=config.mirbase.precursor_ambi_path,
        mature_ambiguous_path=config.mirbase.mature_ambi_path,
        output_path=config.output_dir / f"{config.output_name}.norm",
        taxon_obo_path=config.taxon_obo_path
        
    )
        
