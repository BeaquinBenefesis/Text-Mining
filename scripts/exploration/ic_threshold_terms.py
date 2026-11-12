"""List every ontology term whose normalised structural IC (IC / log N) lies below
a threshold, one TSV per threshold. Sets are cumulative: the 0.30 file contains
the 0.25 file. Graphs are the restricted association-target ontologies from
resources.ONTOLOGY_SOURCES (design notes 13.1, 14.4)."""
import csv
import logging
import math
from textmining.enums import HitType
from textmining.ontology import OntologyGraph
from textmining.paths import OUTPUTS_DIR
from textmining.resources import ONTOLOGY_SOURCES

OUTPUT_DIR = OUTPUTS_DIR / 'ic_threshold_terms'
THRESHOLDS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.45, 0.50)
ENTITY_TYPES = (HitType.DISEASE, HitType.BIOLOGICAL_PROCESS, HitType.CELL,
                HitType.PATHWAY, HitType.TISSUE)


def normalized_ic_terms(graph: OntologyGraph, below: float) -> list[tuple[str, str]]:
    """(term_id, name) for every term with IC / log N < below."""
    log_n = math.log(graph.node_num)
    terms = []
    for idx in graph._rel_subgraph.node_indices():
        if graph.compute_ic_from_index(idx) / log_n < below:
            terms.append((graph.map_idx_to_external_id(idx),
                          graph._rel_subgraph[idx].get('name', '')))
    return terms


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = {t: [] for t in THRESHOLDS}
    for entity_type in ENTITY_TYPES:
        graph = OntologyGraph.from_source(ONTOLOGY_SOURCES[entity_type])
        for threshold in THRESHOLDS:
            terms = sorted(normalized_ic_terms(graph, threshold), key=lambda t: t[1].casefold())
            rows[threshold].extend((entity_type.name, term_id, name) for term_id, name in terms)
            logging.info('%s: %d terms below %.2f', entity_type.name, len(terms), threshold)

    for threshold in THRESHOLDS:
        path = OUTPUT_DIR / f'terms_ic_below_{threshold:.2f}.tsv'
        with path.open('w', newline='') as fh:
            writer = csv.writer(fh, delimiter='\t')
            writer.writerow(('entity_type', 'term_id', 'term_name'))
            writer.writerows(rows[threshold])
        logging.info('Wrote %d terms to %s', len(rows[threshold]), path)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    main()
