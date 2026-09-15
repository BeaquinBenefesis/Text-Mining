import logging
from textmining.logging_utils import setup_logging
from textmining.paths import DB_DIR, OUTPUTS_DIR
from textmining.db.connect import open_for_build
from textmining.db.loaders import (
    entity, synonym, corpus, ontology_closure, association, article_metadata,
    mentions, mirna_history, search,
)
from textmining.resources import ONTOLOGY_SOURCES
from textmining.ontology import OntologyGraph
from textmining.config import MirbaseResources
from textmining.enums import HitType
from textmining.article_utils import MultiArticleReader
import textmining.resources as res

logger = logging.getLogger('textmining.db.build_db')

if __name__ == '__main__':
    setup_logging(output_dir=DB_DIR, run_name='db_build_log')
    con = open_for_build()
    ontology_graphs = {}
    output_name = 'full_run'   # swap this
    output_dir = OUTPUTS_DIR / output_name
    coocs_path = output_dir / f'{output_name}.cooc'
    assoc_path = output_dir / f'{output_name}.assoc'
    norm_path = output_dir / f'{output_name}.norm'
    article_file_pattern = str(res.CORPUS_DIR / "*.sent")

    logger.info("Building from run=%s (coocs=%s, assoc=%s)", output_name, coocs_path, assoc_path)

    # TAXON is skipped, and skipping it here is enough: load_entities,
    # load_synonyms and load_ontology_closure all just iterate ontology_graphs.
    # Taxa are disambiguation context for miRNA normalization
    # (NormalizationContext.get_taxon_relevance) and that work happens at
    # EXTRACTION time, upstream of this database -- by the time .norm exists the
    # species is baked into the accession. Nothing here references a taxon:
    # measured 0 associations, 0 closure rows, 0 mentions, against 2.85M entity
    # and 2.97M synonym rows and 27.5s of graph load. Design notes section 4
    # already excluded taxonomy from the closure for the same semantic reason.
    # If organism rollup is ever wanted it is ~30 curated rows, not 2.85M.
    sources = {t: s for t, s in ONTOLOGY_SOURCES.items() if t is not HitType.TAXON}
    logger.info("Loading %d ontology graph(s) (TAXON skipped)", len(sources))
    for entity_type, source in sources.items():
        logger.info("  %s: loading graph (roots=%s)", entity_type.value, source.roots)
        ontology_graphs[entity_type] = OntologyGraph.from_source(source)

    mirbase_resources = MirbaseResources()

    logger.info("Reading miRBase name history")
    history_rows = (
        mirna_history.read_history(res.MIR_MATURE_HISTORY_PATH, 'mature')
        + mirna_history.read_history(res.MIR_PRECURSOR_HISTORY_PATH, 'precursor')
    )

    with MultiArticleReader(article_file_pattern) as article_reader, con:
        logger.info("Loading entities")
        entity.load_entities(con, mirbase_resources, ontology_graphs, history_rows)

        logger.info("Loading synonyms")
        synonym.load_synonyms(con, ontology_graphs)

        logger.info("Loading miRBase name history")
        mirna_history.load_mirna_name_history(con, history_rows)

        logger.info("Loading legacy miRNA synonyms")
        synonym.load_mirna_legacy_synonyms(con, history_rows)

        logger.info("Loading associations from %s", assoc_path)
        association.load_associations(con, assoc_path)

        logger.info("Loading corpus (article/sentence/association_evidence) from %s", coocs_path)
        corpus.load_corpus(con, coocs_path, article_reader)

        logger.info("Loading ontology closure")
        ontology_closure.load_ontology_closure(con, ontology_graphs)

        # Before article_metadata on purpose: this inserts the articles that have
        # miRNA mentions but never produced a co-occurrence, so the metadata pass
        # that follows backfills year/journal for those too.
        logger.info("Loading mention layer from %s", norm_path)
        mentions.load_mentions(con, norm_path)

        logger.info("Loading article metadata")
        article_metadata.load_article_metadata(con, res.PUBMED_METADATA, res.PMC_METADATA)

        # Needs article.year, so it follows the metadata backfill.
        logger.info("Computing corpus_year")
        mentions.load_corpus_year(con)

        # Last: reads association, ontology_closure, mir_mention_article and synonym.
        logger.info("Building search index")
        search.load_search_names(con)

    logger.info("Build complete, row counts:")
    for table in ("entity", "synonym", "association", "ontology_closure", "article", "sentence",
                  "association_evidence", "mir_mention_article", "mirna_name_history",
                  "corpus_year", "search_name"):
        count = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        logger.info("  %-22s %d", table, count)
