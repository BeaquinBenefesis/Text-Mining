import logging
from textmining.logging_utils import setup_logging
from textmining.paths import DB_DIR, OUTPUTS_DIR
from textmining.db.connect import open_for_build
from textmining.db.loaders import entity, synonym, corpus, ontology_closure, association, article_metadata
from textmining.resources import ONTOLOGY_SOURCES
from textmining.ontology import OntologyGraph
from textmining.config import MirbaseResources
from textmining.article_utils import MultiArticleReader
from textmining.results_io import read_associations_tsv
import textmining.resources as res

logger = logging.getLogger(__name__)

if __name__ == '__main__':
    setup_logging(output_dir=DB_DIR, run_name='db_build_log')
    con = open_for_build()
    ontology_graphs = {}
    output_name = 'mirna_and_disease'   # swap this
    output_dir = OUTPUTS_DIR / output_name
    coocs_path = output_dir / f'{output_name}.cooc'
    assoc_path = output_dir / f'{output_name}.assoc'
    article_file_pattern = str(res.CORPUS_DIR / "*.sent")

    logger.info("Building from run=%s (coocs=%s, assoc=%s)", output_name, coocs_path, assoc_path)

    logger.info("Loading %d ontology graph(s)", len(ONTOLOGY_SOURCES))
    for entity_type, source in ONTOLOGY_SOURCES.items():
        if source.cache_path and source.cache_path.exists():
            logger.info("  %s: loading cached graph from %s", entity_type.value, source.cache_path)
            ontology_graphs[entity_type] = OntologyGraph.load(source.cache_path)
        else:
            logger.info("  %s: no cache, parsing from %s", entity_type.value, source.local_path)
            ontology_graphs[entity_type] = OntologyGraph.from_obo(
                obo_path=source.local_path,
                **source.obo_kwargs
            )

    mirbase_resources = MirbaseResources()

    with MultiArticleReader(article_file_pattern) as article_reader, con:
        logger.info("Loading entities")
        entity.load_entities(con, mirbase_resources, ontology_graphs)

        logger.info("Loading synonyms")
        synonym.load_synonyms(con, ontology_graphs)

        logger.info("Loading associations from %s", assoc_path)
        association.load_associations(con, read_associations_tsv(assoc_path))

        logger.info("Loading corpus (article/sentence/association_evidence) from %s", coocs_path)
        corpus.load_corpus(con, coocs_path, article_reader)

        logger.info("Loading ontology closure")
        ontology_closure.load_ontology_closure(con, ontology_graphs)

        logger.info("Loading article metadata")
        article_metadata.load_article_metadata(con, res.PUBMED_METADATA, res.PMC_METADATA)

    logger.info("Build complete, row counts:")
    for table in ("entity", "synonym", "association", "ontology_closure", "article", "sentence", "association_evidence"):
        count = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        logger.info("  %-20s %d", table, count)
