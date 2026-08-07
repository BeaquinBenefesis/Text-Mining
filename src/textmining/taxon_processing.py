import pandas as pd
from src.textmining.hit_utils import HitsProcessor
import json
from collections import defaultdict
from itertools import combinations
from collections import Counter
import math

class TaxonProcessor:
    def __init__(self, hits_path, synonym_paths, synfile_map, low_memory=False, mu=5):
        self.hits_path = hits_path
        self.synonym_paths = synonym_paths
        self.synfile_map = synfile_map
        #self.relevant_taxons = self._read_relevant_taxons_set(relevant_taxons_path)
        self.low_memory = low_memory

    def compute_ppmi_dict(self, json_out):
        total_article_num = 353028
        occurence_counts = Counter()
        co_occurence_counts = Counter()
        processor = HitsProcessor(self.hits_path, self.synonym_paths, self.synfile_map, low_memory=self.low_memory)
        prev_article = None
        article_taxons = set()
        name_map = {}

        for hit in processor.get_hits(append_article_id=True, sort=True, resolve_ambiguous=True):
            if not hit['resolved']:
                continue                
            
            if prev_article and prev_article != hit['article_id']:
                occurence_counts.update(article_taxons)
                co_occurence_counts.update(tuple(sorted(pair)) for pair in combinations(article_taxons, 2))
                article_taxons.clear()
            

            tax_id = hit['synonym_id']
            if tax_id not in name_map:
                name_map[tax_id] = hit['synonym']
            article_taxons.add(tax_id)
            prev_article = hit['article_id']
        
        if prev_article is not None:
            occurence_counts.update(article_taxons)
            co_occurence_counts.update(tuple(sorted(pair)) for pair in combinations(article_taxons, 2))
        

        pmi_out = {}
        for pair, co_oc_count in co_occurence_counts.items():
            org_a, org_b = pair
            counts_a = occurence_counts[org_a]
            counts_b = occurence_counts[org_b]
            pmi = self._compute_pmi(counts_a, counts_b, co_oc_count, total_article_num)
            pmi_discounted = pmi * self._compute_discount(counts_a, counts_b, co_oc_count)
            string_key = f"{org_a}__{org_b}"
            pmi_out[string_key] = pmi_discounted
        
        sorted_pmi_out = dict(sorted(pmi_out.items(), key=lambda item: item[1], reverse=True))

        with open(json_out, 'w') as f:
            json.dump(sorted_pmi_out, f, indent=3)


    def compute_conditional_prob_dict(self, json_out):
        occurence_counts = Counter()
        co_occurence_counts = Counter()
        processor = HitsProcessor(self.hits_path, self.synonym_paths, self.synfile_map, low_memory=self.low_memory)
        prev_article = None
        article_taxons = set()
        name_map = {}

        for hit in processor.get_hits(append_article_id=True, sort=True, resolve_ambiguous=True):
            if not hit['resolved']:
                continue                
            
            if prev_article and prev_article != hit['article_id']:
                occurence_counts.update(article_taxons)
                co_occurence_counts.update(tuple(sorted(pair)) for pair in combinations(article_taxons, 2))
                article_taxons.clear()
            

            tax_id = hit['synonym_id']
            if tax_id not in name_map:
                name_map[tax_id] = hit['synonym']
            article_taxons.add(tax_id)
            prev_article = hit['article_id']
        
        cond_prob_out = {}
        for pair, co_oc_count in co_occurence_counts.items():
            org_a, org_b = pair
            a_given_b = co_oc_count / occurence_counts[org_a]
            b_given_a = co_oc_count / occurence_counts[org_b]
            string_key_1 = f"{name_map[org_a]}|{name_map[org_b]}"
            string_key_2 = f"{name_map[org_b]}|{name_map[org_a]}"

            cond_prob_out[string_key_1] = a_given_b
            cond_prob_out[string_key_2] = b_given_a

        sorted_prob_out = dict(sorted(cond_prob_out.items(), key=lambda item: item[1], reverse=True))
        with open(json_out, 'w') as f:
            json.dump(sorted_prob_out, f, indent=3)



    def _compute_pmi(self, counts_a, counts_b, joint_count, N):
        pmi_denominator = counts_a * counts_b
        if pmi_denominator > 0:
            return max(0, math.log((joint_count*N) / pmi_denominator, 2))
        else:
            return 0

    def _compute_discount(self, counts_a, counts_b, joint_count):
        joint_count_discount = joint_count / (joint_count + 1)
        marginal_count_discount = min(counts_a, counts_b) / (min(counts_a, counts_b) + 1)
        return joint_count_discount*marginal_count_discount

    def _compute_background_freq(self, taxons_global: dict):
        total = sum(taxons_global.values())
        if total == 0:
            return {}
        return {org: count/total for org, count in taxons_global.items()}


    def _compute_posterior(self,
                        taxon_counts: int, 
                        taxon_corpus_frequency: float, 
                        all_taxon_counts: int
                        ) -> float:
        return (taxon_counts + self.mu*taxon_corpus_frequency) / (all_taxon_counts + self.mu)


    def annotate_corpus(self,
                        hits_path, 
                        synonym_paths, 
                        synfile_map, 
                        json_out):
        processor = HitsProcessor(hits_path, synonym_paths, synfile_map, low_memory=False)
        
        article_to_taxons = defaultdict(lambda: defaultdict(int))
        taxons_global = {taxon: 0 for taxon in self.relevant_taxons}
        output = {}


        # Read hits, calculate global and article level counts
        print('Reading hits')
        for hit in processor.get_hits(remove_sent_id_prefix=True, append_article_id=True):
            article_id = hit['article_id']
            taxon_id = hit['synonym_id']

            if not taxon_id in self.relevant_taxons:
                continue

            article_to_taxons[article_id][taxon_id] += 1
            taxons_global[taxon_id] += 1
        
        # Compute global frequencies, our prior
        background_freq = self._compute_background_freq(taxons_global)
        with open('test.json', 'w', encoding='utf-8') as test:
            json.dump(sorted(background_freq.items(), key=lambda item: item[1], reverse=True), test, indent=4)

        print('Calculating posteriors')
        for article_id, taxon_dict in article_to_taxons.items():
            posteriors = {}
            all_taxon_counts = sum(taxon_dict.values())
            for taxon_id in self.relevant_taxons:
                global_freq = background_freq.get(taxon_id, 0.0)
                count = taxon_dict.get(taxon_id, 0)
                posteriors[taxon_id] = self._compute_posterior(taxon_counts=count, taxon_corpus_frequency=global_freq, all_taxon_counts=all_taxon_counts)
            
            top_5_posteriors = dict(sorted(posteriors.items(), key=lambda item: item[1], reverse=True)[:5])
            output[article_id] = {'counts' : taxon_dict, 'posteriors': top_5_posteriors}

        with open(json_out, 'w', encoding='utf-8') as file:
            json.dump(output, file, indent=4)

    # File containing NCBI ids, one entry per line
    def _read_relevant_taxons_set(self, relevant_taxons_path) -> set:
        return set(pd.read_csv(relevant_taxons_path, header=None).iloc[0:, 0])
    
    def _calculate_section_weight(self, sent_id):
        pass



print('Meep')
hits_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/linnaeus_hits/linnaeus_hits.hits'
synfile_map = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/linnaeus_hits/synfile.map'
basepath = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/taxonomy_no_dups/'
file_names = ['linnaeus_cell_lines.syn', 'linnaeus_proxy.syn', 'linnaeus_species.syn']
synfile_paths = (basepath + file_name for file_name in file_names)
processor = TaxonProcessor(hits_path=hits_path, synonym_paths=synfile_paths, synfile_map=synfile_map, low_memory=False)
processor.compute_conditional_prob_dict('cond_prob.json')