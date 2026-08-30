from textmining.config import PipelineConfig, ExistingSyngrepPipelineConfig, EntityConfig
from textmining.syngrep import run_syngrep
from textmining.scoring import HitScorer
from textmining.core import Processor
from textmining.hit_utils import HitProcessor
from textmining.article_utils import MultiArticleReader
from textmining.progress import track_progress
from textmining.results_io import write_normalized_hits_tsv, write_associations_tsv
from textmining.syngrep import SynGrepResult
from textmining.logging_utils import setup_logging
from textmining.analysis import EvidenceAggregator, Grouper
import logging
from pathlib import Path


def run_pipeline(config: PipelineConfig, debug=logging.INFO):
    setup_logging(output_dir = config.output_dir,
                  run_name = config.output_name,
                  level=debug
                  )
    syngrep_result = run_syngrep(
        sentence_pattern=config.sentence_pattern,
        synonyms=config.synonym_paths,
        output_dir=config.output_dir,
        abbrev_synonyms=config.abbrev_paths,
        within_word=config.within_word,
        output_name=config.output_name,
        word_char=config.word_char,
        ntasks=config.n_tasks,
        abbrev_mode=config.abbrev_mode,
        no_abbrev_syn_list=config.no_abbrev_file_names,
    )

    process_hits(
        output_name=config.output_name,
        output_dir=config.output_dir,
        entity_configs=config.entity_configs,
        sentence_pattern=config.sentence_pattern,
        syngrep_results=syngrep_result
    )


def run_existing_pipeline(config: ExistingSyngrepPipelineConfig, debug=logging.INFO):
    setup_logging(output_dir = config.output_dir,
                      run_name = config.output_name,
                      level=debug
                      )
    process_hits(
        output_name=config.output_name,
        output_dir=config.output_dir,
        sentence_pattern=config.sentence_pattern,
        syngrep_results=config.syngrep_result,
        entity_configs=config.entity_configs
    )


def process_hits(output_name : str,
                 output_dir : Path,
                 entity_configs: list[EntityConfig],
                 sentence_pattern: str,
                 syngrep_results: SynGrepResult):
    type_to_ontology = {}
    normalizers = {}

    for entity_config in entity_configs:
        type_to_ontology[entity_config.entity_type] = entity_config.get_graph()
        normalizers[entity_config.entity_type] = entity_config.get_normalizer()

    scorer = HitScorer(type_to_ontology=type_to_ontology)
    hit_processor = HitProcessor(
        hits_path=syngrep_results.hits_path,
        synfile_map=syngrep_results.synfile_map_path,
        synfile_type_map=syngrep_results.synfile_type_map_path,
        type_to_ontology=type_to_ontology,
        low_memory=False
    )
    main_processor = Processor(hits_processor=hit_processor,
                               normalizers=normalizers,
                               scorer=scorer,
                               article_reader=MultiArticleReader(sentence_pattern),)
    aggregator = EvidenceAggregator()
    article_stream = track_progress(main_processor.get_normalized_article_stream(), label='articles', report_every=1000)
    article_stream = _tap_associations(article_stream, aggregator)
    write_normalized_hits_tsv(article_stream, output_dir / f'{output_name}.norm')
    write_associations_tsv(aggregator.associations.values(), output_dir / f'{output_name}.assoc')

def _tap_associations(article_stream, aggregator: EvidenceAggregator):
    for article in article_stream:
        # TODO: Check that normalized hits dont contain blacklisted/unresovled hits etc
        cooccs = Grouper.extract_cooccurrences(iter(article.normalized_hits))
        for cooc in cooccs:
            aggregator.record_coccurrence(cooc)
        yield article