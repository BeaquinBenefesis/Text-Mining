import argparse
import logging
from pathlib import Path
from textmining.logging_utils import setup_logging
from textmining.paths import DB_DIR, OUTPUTS_DIR
from textmining.db.connect import open_for_build, DB_PATH
from textmining.db import exports
from textmining.db.loaders import (
    entity, synonym, corpus, ontology_closure, association, article_metadata,
    mentions, mirna_history, search, gene, mirna_stats,
)
from textmining.resources import ONTOLOGY_SOURCES
from textmining.ontology import OntologyGraph
from textmining.config import MirbaseResources
from textmining.enums import HitType
from textmining.article_utils import MultiArticleReader
import textmining.resources as res

logger = logging.getLogger('textmining.db.build_db')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Build the knowledgebase database from one pipeline run.")
    parser.add_argument("--run", default="new_full_run_w_genes",
                        help="run name: reads outputs/<run>/<run>.{assoc,cooc,labels,norm}")
    parser.add_argument("--run-dir", type=Path, help="directory holding the run's files (default: outputs/<run>)")
    parser.add_argument("--db", type=Path, default=DB_PATH,
                        help="database to write; an existing file is replaced (default: db/atlas.db)")
    args = parser.parse_args()

    setup_logging(output_dir=DB_DIR, run_name='db_build_log')
    con = open_for_build(args.db)
    ontology_graphs = {}
    output_name = args.run
    output_dir = args.run_dir or OUTPUTS_DIR / output_name
    coocs_path = output_dir / f'{output_name}.cooc'
    labels_path = output_dir / f'{output_name}.labels'
    assoc_path = output_dir / f'{output_name}.assoc'
    norm_path = output_dir / f'{output_name}.norm'
    article_file_pattern = str(res.CORPUS_DIR / "*.sent")

    logger.info("Building from run=%s (coocs=%s, assoc=%s)", output_name, coocs_path, assoc_path)

    # TAXON is skipped, the user cant query for taxon entities and it is not referenced from any associations
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

        logger.info("Loading genes from %s", res.GENE_SYNS)
        gene.load_gene_entities(con, res.GENE_SYNS, res.GENE_SYNS_RAW, res.GENE_ORGANISM_MAP)
        gene.load_gene_synonyms(con, res.GENE_SYNS)

        logger.info("Loading miRBase name history")
        mirna_history.load_mirna_name_history(con, history_rows)

        logger.info("Loading legacy miRNA synonyms")
        synonym.load_mirna_legacy_synonyms(con, history_rows)

        logger.info("Loading associations from %s", assoc_path)
        association.load_associations(con, assoc_path)

        logger.info("Loading corpus (article/sentence/mention_pair/association_evidence) from %s and %s", coocs_path, labels_path)
        corpus.load_corpus(con, coocs_path, labels_path, article_reader)

        # Needs association_evidence and mention_pair.
        logger.info("Loading association labels")
        association.load_association_labels(con)

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

        # Needs association and mir_mention_article.
        logger.info("Ranking miRNAs by article count")
        mirna_stats.load_mirna_stats(con)

        # Last: reads association, ontology_closure, mir_mention_article and synonym.
        logger.info("Building search index")
        search.load_search_names(con)

    logger.info("Build complete, row counts:")
    for table in ("entity", "synonym", "association", "ontology_closure", "article", "sentence",
                  "mention_pair", "association_evidence", "association_label", "mir_mention_article", "mirna_name_history",
                  "corpus_year", "mirna_stats", "search_name"):
        count = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        logger.info("  %-22s %d", table, count)

    downloads_dir = args.db.parent / "downloads"
    logger.info("Writing download files to %s", downloads_dir)
    exports.export_hits(norm_path, downloads_dir)
    exports.export_associations(con, downloads_dir)
