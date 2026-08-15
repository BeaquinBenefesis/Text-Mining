from textmining.config import DiseasePipelineConfig, ExistingSyngrepDiseaseConfig
from textmining.syngrep import run_syngrep
from textmining.hit_utils import HitProcessor
from textmining.ontology import OntologyGraph
from textmining.models import HitType
from textmining.normalization import DefaultNormalizer
from textmining.scoring import HitScorer
from textmining.core import Processor
from textmining.results_io import write_normalized_hits_tsv
from textmining.progress import track_progress
from textmining.logging_utils import setup_logging

def process_disease_hits(
    hits_path,
    synfile_map_path,
    synfile_type_map_path,
    disease_obo_path,
    output_path,
):
    disease_graph = OntologyGraph.from_obo(disease_obo_path, exclude_gci=True)
    type_to_ontology = {HitType.DISEASE: disease_graph}
    hits_processor = HitProcessor(hits_path=hits_path, 
                                  synfile_map=synfile_map_path, 
                                  synfile_type_map=synfile_type_map_path,
                                  type_to_ontology=type_to_ontology)
    default_normalizer = DefaultNormalizer()
    normalizers = {
        HitType.DISEASE: default_normalizer
    }
    scorer = HitScorer(type_to_ontology=type_to_ontology)
    
    main_processor = Processor(hits_processor=hits_processor,
                               normalizers=normalizers,
                               scorer=scorer)
    article_stream = track_progress(main_processor.get_normalized_article_stream(), label='articles', report_every=1000)
    write_normalized_hits_tsv(article_stream,
                              output_path)

def run_disease_pipeline(output_name: str):
    config = DiseasePipelineConfig(output_name=output_name)
    setup_logging(
        output_dir=config.output_dir,
        run_name=output_name
    )
    res = run_syngrep(
        ntasks=config.n_tasks,
        sentence_pattern=config.sentence_pattern,
        synonyms=config.synonyms,
        abbrev_synonyms=config.abbrev_synonyms,
        output_dir=config.output_dir,
        output_name=config.output_name,
        abbrev=config.abbrev,
        word_char=config.word_char
    )
    process_disease_hits(
        hits_path=res.hits_path,
        synfile_map_path=res.synfile_map_path,
        synfile_type_map_path=res.synfile_type_map_path,
        disease_obo_path=config.disease_obo_path,
        output_path=config.output_dir / f"{config.output_name}.norm",
    )

def run_existing_disease_pipeline(config: ExistingSyngrepDiseaseConfig):
    setup_logging(
        output_dir=config.output_dir,
        run_name=config.output_name
    )
    process_disease_hits(
        hits_path=config.hits_path,
        synfile_map_path=config.synfile_map_path,
        synfile_type_map_path=config.synfile_type_map_path,
        disease_obo_path=config.disease_obo_path,
        output_path=config.output_dir / f"{config.output_name}.norm",
    )

