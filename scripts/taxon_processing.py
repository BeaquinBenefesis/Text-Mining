import pandas as pd
from hitsUtils import HitsProcessor
import json
import argparse
from collections import defaultdict
import numpy as np


mu = 5

def compute_background_freq(taxons_global: dict):
    total = sum(taxons_global.values())
    if total == 0:
        return {}
    return {org: count/total for org, count in taxons_global.items()}


def compute_posterior(taxon_counts: int, 
                      taxon_corpus_frequency: float, 
                      all_taxon_counts: int
                      ) -> float:
    return (taxon_counts + mu*taxon_corpus_frequency) / (all_taxon_counts + mu)


def annotate_corpus(taxon_hits_path, 
                    taxon_syn_path, 
                    relevant_taxons_path, 
                    json_out):
    processor = HitsProcessor(taxon_hits_path, taxon_syn_path, low_memory=False)
    relevant_taxons = read_relevant_taxons_set(relevant_taxons_path) if relevant_taxons_path else None
    
    article_to_taxons = defaultdict(lambda: defaultdict(int))
    taxons_global = {taxon: 0 for taxon in relevant_taxons}
    output = {}


    # Read hits, calculate global and article level counts
    print('Reading hits')
    for hit in processor.get_hits(remove_sent_id_prefix=True, append_article_id=True):
        article_id = hit['article_id']
        taxon_id = hit['synonym_id']

        if relevant_taxons_path and not taxon_id in relevant_taxons:
            continue

        article_to_taxons[article_id][taxon_id] += 1
        taxons_global[taxon_id] += 1
    
    # Compute global frequencies, our prior
    background_freq = compute_background_freq(taxons_global)
    with open('test.json', 'w', encoding='utf-8') as test:
        json.dump(sorted(background_freq.items(), key=lambda item: item[1], reverse=True), test, indent=4)

    print('Calculating posteriors')
    for article_id, taxon_dict in article_to_taxons.items():
        posteriors = {}
        all_taxon_counts = sum(taxon_dict.values())
        for taxon_id in relevant_taxons:
            global_freq = background_freq.get(taxon_id, 0.0)
            count = taxon_dict.get(taxon_id, 0)
            posteriors[taxon_id] = compute_posterior(taxon_counts=count, taxon_corpus_frequency=global_freq, all_taxon_counts=all_taxon_counts)
        
        top_5_posteriors = dict(sorted(posteriors.items(), key=lambda item: item[1], reverse=True)[:5])
        output[article_id] = {'counts' : taxon_dict, 'posteriors': top_5_posteriors}

    with open(json_out, 'w', encoding='utf-8') as file:
        json.dump(output, file, indent=4)

# File containing NCBI ids, one entry per line
def read_relevant_taxons_set(relevant_taxons_path) -> set:
    return set(pd.read_csv(relevant_taxons_path, header=None).iloc[0:, 0])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Computes a mapping from article id, to tax ids and their respective counts."
    )

    parser.add_argument(
        "-out", metavar="out", required=True, help="Path to output file."
    )

    parser.add_argument(
        "-taxon_hits", metavar="taxon_hits", required=True, help="Path to taxon hits file."
    )

    parser.add_argument(
        "-taxon_syns", metavar="out", required=True, help="Path to taxon synonyms file."
    )

    parser.add_argument(
        "-filter", metavar="out", required=False, help="Path to filter file. If provided, the hits will be filtered to only include taxons mentioned in filter file."
    )

    args = parser.parse_args()
    annotate_corpus(args.taxon_hits, args.taxon_syns, args.filter, args.out)