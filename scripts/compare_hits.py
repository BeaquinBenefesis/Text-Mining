import argparse
import os
from collections import defaultdict


def extract_sentence_to_synonyms(hits_file):
    sentence_to_synonyms = defaultdict(list)

    with open(hits_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            columns = line.split("\t")
            if len(columns) < 1:
                continue

            article, sentence_id = columns[0].split(':')
            synonym = columns[2]
            sentence_to_synonyms[sentence_id].append(synonym)
    return sentence_to_synonyms

def compare_hits(hits1, hits2, out_dir):
    # Get unique sentence hits and the synonyms they contain
    sentence_to_synonyms1 = extract_sentence_to_synonyms(hits1)
    sentence_to_synonyms2 = extract_sentence_to_synonyms(hits2)

    # Get the sets of unique sentence hits
    sent_ids1 = set(sentence_to_synonyms1.keys())
    sent_ids2 = set(sentence_to_synonyms2.keys())

    hits1_name = os.path.basename(hits1)
    hits2_name = os.path.basename(hits2)

    # Difference metrics
    intersect = sent_ids1 & sent_ids2
    sym_diff = sent_ids1 ^ sent_ids2
    only_in_hits1 = sent_ids1 - sent_ids2
    only_in_hits2 = sent_ids2 - sent_ids1

    print(f"{hits1_name}: {len(sent_ids1)} sentence hits found.")
    print(f"{hits2_name}: {len(sent_ids2)} sentence hits found.")
    print(f"Shared sentence hits: {len(intersect)}")
    print(f"Differing sentence hits: {len(sym_diff)}")
    print(f"Only in {hits1_name}: {len(only_in_hits1)}")
    print(f"Only in {hits2_name}: {len(only_in_hits2)}")

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

        with open(os.path.join(out_dir, f"{hits1_name}_unique.txt"), "w") as f:
            for hit in only_in_hits1:
                synonyms = sentence_to_synonyms1[hit]
                syn_string = '\t'.join(synonyms)
                f.write(f"{hit}\t{syn_string}\n")

        with open(os.path.join(out_dir, f"{hits2_name}_unique.txt"), "w") as f:
            for hit in only_in_hits2:
                synonyms = sentence_to_synonyms2[hit]
                syn_string = '\t'.join(synonyms)
                f.write(f"{hit}\t{syn_string}\n")
        


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-hits1", metavar="hits1", required=True)
    parser.add_argument("-hits2", metavar="hits2", required=True)
    parser.add_argument("-out_dir", metavar="out_dir", required=False)

    args = parser.parse_args()
    hits1 = args.hits1
    hits2 = args.hits2
    out_dir = args.out_dir
    compare_hits(hits1, hits2, out_dir)