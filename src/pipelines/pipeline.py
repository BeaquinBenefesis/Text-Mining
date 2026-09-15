from textmining.config import PipelineConfig, ExistingSyngrepPipelineConfig, EntityConfig
from textmining.enums import HitType
from textmining.syngrep import run_syngrep
from textmining.scoring import HitScorer
from textmining.core import Processor
from textmining.hit_utils import HitProcessor
from textmining.article_utils import MultiArticleReader
from textmining.progress import track_progress
from textmining.results_io import write_cooccurrences_tsv, write_normalized_hits_tsv, write_associations_tsv, read_normalized_hits, read_normalized_hits_tsv
from textmining.syngrep import SynGrepResult
from textmining.logging_utils import setup_logging
from textmining.analysis import EvidenceAggregator, Grouper
from textmining.normalization import normalized_successfully
from textmining.models import NormalizedHit, CoOccurence
import logging
from pathlib import Path
from typing import Iterator

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
                 syngrep_results: SynGrepResult) -> EvidenceAggregator:
    type_to_ontology = {c.entity_type: c.get_graph() for c in entity_configs}
    normalizers = {c.entity_type: c.get_normalizer() for c in entity_configs}

    processor = Processor(
        hits_processor=HitProcessor(
            hits_path=syngrep_results.hits_path,
            synfile_map=syngrep_results.synfile_map_path,
            synfile_type_map=syngrep_results.synfile_type_map_path,
            type_to_ontology=type_to_ontology,
            low_memory=False,
            mir_normalizer=normalizers.get(HitType.MIR),
        ),
        normalizers=normalizers,
        scorer=HitScorer(type_to_ontology=type_to_ontology),
        article_reader=MultiArticleReader(sentence_pattern),
    )

    hits = (hit
            for article in processor.get_normalized_article_stream()
            for hit in article.normalized_hits)
    hits = write_normalized_hits_tsv(hits, output_dir / f'{output_name}.norm')
    hits = track_progress(hits, label='hits', report_every=100_000)

    cooccurrences = Grouper.extract_cooccurrences(_successfully_normalized(hits))
    cooccurrences = write_cooccurrences_tsv(cooccurrences, output_dir / f'{output_name}.cooc')

    aggregator = _aggregate_associations(cooccurrences, type_to_ontology)
    write_associations_tsv(aggregator.associations.values(), output_dir / f'{output_name}.assoc')
    return aggregator


def _successfully_normalized(hits: Iterator[NormalizedHit]) -> Iterator[NormalizedHit]:
    """Pre-filter; Grouper.extract_valid_combinations applies the same predicate per pair."""
    return (h for h in hits if normalized_successfully(h))


def _aggregate_associations(cooccurrences: Iterator[CoOccurence], type_to_ontology, propagate: bool = True) -> EvidenceAggregator:
    aggregator = EvidenceAggregator(type_to_ontology, propagate=propagate)
    for cooc in cooccurrences:
        aggregator.record_coccurrence(cooc)
    return aggregator


def run_from_normalized_output(entity_configs: list[EntityConfig], norm_hits_pattern: str, output_name: str, output_dir: str | Path,
                               propagate: bool = True, duck=True, debug=logging.INFO) -> EvidenceAggregator:
    '''Run aggregation + scoring from existing hits files, duck=True uses duckDB to merge/sort over multiple files.
    If duck=False, norm_hits_pattern needs to point to a single file.
    propagate=False builds direct-only associations (the ablation); no ontology graph is loaded then.
    Use a different output_name than the extraction run: the .cooc file is re-derived and written.'''
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
    logger.info('  propagate: %s', propagate)

    # Only association target types need a graph (not MIR, not TAXON), and only when propagating.
    target_configs = [c for c in entity_configs if Grouper.valid_types(HitType.MIR, c.entity_type)] if propagate else []
    type_to_ontology = {c.entity_type: c.get_graph() for c in target_configs}
    logger.info('  graphs loaded: %s', [t.name for t in type_to_ontology] or 'none')

    hit_stream = read_normalized_hits(norm_hits_pattern) if duck else read_normalized_hits_tsv(Path(norm_hits_pattern))
    successfully_normed_hits = _successfully_normalized(hit_stream)

    coocs = write_cooccurrences_tsv(Grouper.extract_cooccurrences(successfully_normed_hits), output_path=output_dir / f'{output_name}.cooc')
    aggregator = _aggregate_associations(coocs, type_to_ontology, propagate=propagate)

    write_associations_tsv(aggregator.associations.values(), assoc_path)
    if not aggregator.associations:
        logger.warning('No associations produced - check that the run covers at least two entity types')

    return aggregator