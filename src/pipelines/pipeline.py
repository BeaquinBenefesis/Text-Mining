from textmining.config import PipelineConfig, ExistingSyngrepPipelineConfig, EntityConfig
from textmining.enums import HitType
from textmining.syngrep import run_syngrep
from textmining.scoring import HitScorer
from textmining.core import Processor
from textmining.hit_utils import HitProcessor
from textmining.article_utils import MultiArticleReader
from textmining.progress import track_progress
from textmining.results_io import write_normalized_hits_tsv, write_associations_tsv, read_normalized_hits, read_normalized_hits_tsv
from textmining.syngrep import SynGrepResult
from textmining.logging_utils import setup_logging
from textmining.analysis import EvidenceAggregator, Grouper
from textmining.normalization import normalized_successfully
import logging
import time
from collections import Counter
from pathlib import Path

# setup_logging configures the 'textmining' logger; this module is not under that
# package, so name the logger explicitly or its records never reach the handlers.
logger = logging.getLogger('textmining.pipeline')


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
        low_memory=False,
        mir_normalizer=normalizers.get(HitType.MIR)
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

def _tap_normalized(hits, stats: Counter):
    '''Filter to successfully normalized hits, counting both sides.

    Grouper.extract_valid_combinations applies the same predicate internally;
    hoisting it here is a pure optimisation (verified identical scores) and gives
    the normalization rate for the run log.
    '''
    for hit in hits:
        stats['hits'] += 1
        stats[f'hits_{hit.entity_type.name}'] += 1
        if normalized_successfully(hit):
            stats['kept'] += 1
            yield hit


def run_from_normalized_output(norm_hits_pattern: str, output_name: str, output_dir: str | Path, duck=True, debug=logging.INFO) -> EvidenceAggregator:
    '''Run aggregation + scoring from existing hits files, duck=True uses duckDB to merge/sort over multiple files.
    If duck=False, norm_hits_pattern needs to point to a single file.'''
    output_dir = Path(output_dir)
    
    log_path = setup_logging(output_dir = output_dir,
                run_name = output_name,
                level=debug
                )
    
    assoc_path = output_dir / f'{output_name}.assoc'
    logger.info('Rebuilding associations from normalized output')
    logger.info('  source: %s (reader=%s)', norm_hits_pattern, 'duckdb' if duck else 'csv')
    logger.info('  output: %s', assoc_path)
    logger.info('  log:    %s', log_path)
    start = time.perf_counter()

    hit_stream = read_normalized_hits(norm_hits_pattern) if duck else read_normalized_hits_tsv(Path(norm_hits_pattern))
    stats = Counter()
    successfully_normed_hits = _tap_normalized(hit_stream, stats)

    aggregator = EvidenceAggregator()
    for cooc in Grouper.extract_cooccurrences(successfully_normed_hits):
        stats['cooccurrences'] += 1
        aggregator.record_coccurrence(cooc)

    write_associations_tsv(aggregator.associations.values(), assoc_path)

    hits, kept = stats['hits'], stats['kept']
    logger.info('Read %d hits (%s)', hits,
                ', '.join(f'{k.removeprefix("hits_")}={v}' for k, v in sorted(stats.items()) if k.startswith('hits_')))
    logger.info('Kept %d normalized hits (%.1f%%)', kept, 100.0 * kept / hits if hits else 0.0)
    logger.info('Recorded %d co-occurrences -> %d associations in %.1fs',
                stats['cooccurrences'], len(aggregator.associations), time.perf_counter() - start)
    if not aggregator.associations:
        logger.warning('No associations produced - check that the run covers at least two entity types')

    return aggregator