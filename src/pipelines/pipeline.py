from textmining.config import BasePipelineConfig, ExistingSyngrepPipelineConfig, EntityConfig
from textmining.enums import HitType, Label
from textmining.syngrep import run_syngrep
from textmining.scoring import HitScorer
from textmining.core import Processor
from textmining.hit_utils import HitProcessor
from textmining.article_utils import MultiArticleReader
from textmining.progress import track_progress
from textmining.results_io import (write_cooccurrences_tsv, write_normalized_hits_tsv, write_associations_tsv, write_labels_tsv,
                                   read_cooccurrences_tsv, read_labels_tsv, read_normalized_hits, read_normalized_hits_tsv)
from textmining.syngrep import SynGrepResult
from textmining.logging_utils import setup_logging
from textmining.analysis import EvidenceAggregator, Grouper
from textmining.consistency import OrganismConsistencyFilter
from textmining.normalization import normalized_successfully
from textmining.models import NormalizedHit, CoOccurence, PairLabels
import logging
from itertools import groupby, tee
from pathlib import Path
from typing import Iterator

logger = logging.getLogger('textmining.pipeline')

def run_pipeline(config: BasePipelineConfig, label_relations: bool = True, debug=logging.INFO) -> EvidenceAggregator:
    """All three steps: co-occurrences, relation labels, associations.
    label_relations=False skips step 2 and builds unweighted associations."""
    extract_cooccurrences(config, debug)
    # a run without term types (miRNA only) has no co-occurrences to label
    label_relations = label_relations and any(Grouper.valid_types(HitType.MIR, c.entity_type)
                                              for c in config.entity_configs)
    if label_relations:
        annotate_cooccurrences(config, debug)
    return aggregate_associations(config, weighted=label_relations, debug=debug)


def run_existing_pipeline(config: ExistingSyngrepPipelineConfig, debug=logging.INFO) -> EvidenceAggregator:
    """run_pipeline on existing syngrep output."""
    return run_pipeline(config, debug=debug)


def extract_cooccurrences(config: BasePipelineConfig, debug=logging.INFO) -> Path:
    """Step 1: syngrep hits -> normalized hits -> co-occurrences."""
    setup_logging(output_dir=config.output_dir, run_name=f'{config.output_name}_extract', level=debug)
    if isinstance(config, ExistingSyngrepPipelineConfig):
        syngrep_results = config.syngrep_result
    else:
        syngrep_results = run_syngrep(
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

    graphs = {c.entity_type: c.get_graph() for c in config.entity_configs}
    type_to_ontology = {t: g for t, g in graphs.items() if g is not None}
    resolvers = {c.entity_type: r for c in config.entity_configs
                 if (r := c.get_resolver(graphs[c.entity_type])) is not None}
    normalizers = {c.entity_type: c.get_normalizer() for c in config.entity_configs}

    processor = Processor(
        hits_processor=HitProcessor(
            hits_path=syngrep_results.hits_path,
            synfile_map=syngrep_results.synfile_map_path,
            synfile_type_map=syngrep_results.synfile_type_map_path,
            resolvers=resolvers,
            low_memory=False,
            mir_normalizer=normalizers.get(HitType.MIR),
        ),
        normalizers=normalizers,
        scorer=HitScorer(type_to_ontology=type_to_ontology),
        # the score is the ontology IC, so types without a graph (genes) have none
        no_score={HitType.MIR} | {t for t, g in graphs.items() if g is None},
        article_reader=MultiArticleReader(config.sentence_pattern),
    )

    hits = (hit
            for article in processor.get_normalized_article_stream()
            for hit in article.normalized_hits)
    hits = write_normalized_hits_tsv(hits, _output_path(config, 'norm'))
    hits = track_progress(hits, label='hits', report_every=100_000)

    cooc_path = _output_path(config, 'cooc')
    cooccurrences = Grouper.extract_cooccurrences(_successfully_normalized(hits))
    configs = {c.entity_type: c for c in config.entity_configs}
    if HitType.GENE in configs:
        consistency = OrganismConsistencyFilter.load(configs[HitType.MIR].mirbase, configs[HitType.GENE].taxon_map,
                                                     resolvers[HitType.TAXON])
        cooccurrences = consistency.filter(cooccurrences)
    # the writers pass their input through: consuming the stream writes both files
    for _ in write_cooccurrences_tsv(cooccurrences, cooc_path):
        pass
    if HitType.GENE in configs:
        logger.info("Consistency filter dropped %d co-occurrence(s)", consistency.dropped)
    return cooc_path


def annotate_cooccurrences(config: BasePipelineConfig, debug=logging.INFO) -> Path:
    """Step 2: co-occurrences -> relation label probabilities per mention pair."""
    from textmining.bert import RelationAnnotator   # loads torch

    setup_logging(output_dir=config.output_dir, run_name=f'{config.output_name}_annotate', level=debug)
    annotator = RelationAnnotator()
    labels_path = _output_path(config, 'labels')

    with MultiArticleReader(config.sentence_pattern) as reader:
        pairs = _distinct_mention_pairs(read_cooccurrences_tsv(_output_path(config, 'cooc')))
        pairs = track_progress(pairs, label='mention pairs', report_every=10_000)
        pairs, to_annotate = tee(pairs)
        probabilities = annotator.annotate(_model_inputs(to_annotate, reader))
        pair_labels = (PairLabels(pair.sentence_id, pair.entity_positions, pair.entity_types[1], pair_probabilities)
                       for pair, pair_probabilities in zip(pairs, probabilities))
        write_labels_tsv(pair_labels, annotator.labels, labels_path)
    return labels_path


def aggregate_associations(config: BasePipelineConfig, weighted: bool = True, propagate: bool = True,
                           debug=logging.INFO) -> EvidenceAggregator:
    """Step 3: co-occurrences, weighted by their labels -> associations.
    weighted = False ignores the labels
    propagate = False builds direct-only associations"""
    setup_logging(output_dir=config.output_dir, run_name=f'{config.output_name}_aggregate', level=debug)
    # only term types (not MIR, not TAXON) have associations, and only those with a graph propagate
    term_configs = [c for c in config.entity_configs if Grouper.valid_types(HitType.MIR, c.entity_type)] if propagate else []
    type_to_ontology = {c.entity_type: g for c in term_configs if (g := c.get_graph()) is not None}

    cooccurrences = read_cooccurrences_tsv(_output_path(config, 'cooc'))
    if weighted:
        cooccurrences = _weight_by_labels(cooccurrences, read_labels_tsv(_output_path(config, 'labels')))

    aggregator = _aggregate_associations(cooccurrences, type_to_ontology, propagate=propagate)
    write_associations_tsv(aggregator.associations.values(), _output_path(config, 'assoc'))
    return aggregator


def _output_path(config: BasePipelineConfig, suffix: str) -> Path:
    return Path(config.output_dir) / f'{config.output_name}.{suffix}'


def _distinct_mention_pairs(cooccurrences: Iterator[CoOccurence]) -> Iterator[CoOccurence]:
    """The first co-occurrence of every mention pair. The co-occurrences of a sentence are contiguous."""
    for _, sentence_coocs in groupby(cooccurrences, key=lambda cooc: cooc.sentence_id):
        seen = set()
        for cooc in sentence_coocs:
            if cooc.mention_key not in seen:
                seen.add(cooc.mention_key)
                yield cooc


def _model_inputs(pairs: Iterator[CoOccurence], reader: MultiArticleReader) -> Iterator[tuple]:
    """(text, mirna_span, term_span, term_type) of each mention pair, as RelationAnnotator.annotate takes them."""
    article, sentences = None, {}
    for pair in pairs:
        # articles are contiguous too, so only the current one is kept
        if (pair.origin_file_name, pair.article_id) != article:
            article = (pair.origin_file_name, pair.article_id)
            sentences = reader.fetch_article(*article)
        yield (sentences[pair.sentence_id], *pair.entity_positions, pair.entity_types[1])


def _weight_by_labels(cooccurrences: Iterator[CoOccurence], pair_labels: Iterator[PairLabels]) -> Iterator[CoOccurence]:
    labels_by_sentence = groupby(pair_labels, key=lambda pair: pair.sentence_id)
    for sentence_id, sentence_coocs in groupby(cooccurrences, key=lambda cooc: cooc.sentence_id):
        label_sentence_id, sentence_labels = next(labels_by_sentence, (None, ()))
        if label_sentence_id != sentence_id:
            raise ValueError(f'.labels does not match .cooc at sentence {sentence_id}: rerun annotate_cooccurrences')
        probabilities = {pair.mention_key: pair.probabilities for pair in sentence_labels}
        for cooc in sentence_coocs:
            pair_probabilities = probabilities[cooc.mention_key]
            if pair_probabilities is not None:      # a pair that could not be labelled counts fully
                cooc.weight = 1 - pair_probabilities[Label.NONE]
            yield cooc


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