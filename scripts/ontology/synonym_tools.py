import os
from collections import defaultdict, Counter

def read_synfile(file) -> defaultdict:
    line_count = 0
    syn_count = 0
    out = defaultdict(set)
    all_terms_counter = Counter()

    with open(file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line: continue

            syn_id, syns_raw = line.split(':', 1)
            syns = syns_raw.split('|')

            out[syn_id].update(syns)
            all_terms_counter.update(syns)

            line_count += 1
            syn_count += len(syns)

    print(f'{os.path.basename(file)}: Read {line_count} lines with {syn_count} terms.')

    duplicates = {term: count for term, count in all_terms_counter.items() if count > 1}

    if duplicates:
        print("\nTerms appearing more than once:")
        for term, count in sorted(duplicates.items(), key=lambda x: x[1], reverse=True):
            print(f"  '{term}': {count} times")
    else:
        print("\nNo duplicate terms found.")

    return out

def compare_synfiles(file_1, file_2, print_overlapping=False):
    dict_1 = read_synfile(file_1)
    dict_2 = read_synfile(file_2)

    ids_1 = set(dict_1.keys())
    ids_2 = set(dict_2.keys())

    terms_1 = {term.lower() for synonyms in dict_1.values() for term in synonyms}
    terms_2 = {term.lower() for synonyms in dict_2.values() for term in synonyms}

    print(f'{os.path.basename(file_1)}: {len(ids_1)} unique ids with {len(terms_1)} unique synonyms')
    print(f'{os.path.basename(file_2)}: {len(ids_2)} unique ids with {len(terms_2)} unique synonyms')

    overlapping_ids = ids_1 & ids_2
    overlapping_terms = terms_1 & terms_2
    print(f'Number of overlapping ids: {len(overlapping_ids)}')
    print(f'Number of overlapping terms: {len(overlapping_terms)}')

    if print_overlapping:
        out_id = "\n".join((overlapping_ids))
        out_term = "\n".join((overlapping_terms))
        print(f'Overlapping ids: {out_id}')
        print(f'Overlapping terms: {out_term}')

# Normalize everything to lowercase
def compute_ambisyn_dict(syn_paths) -> dict:
    flipped = defaultdict(set)
    for path in syn_paths:
        for term_id, terms in get_syn_line_terms(path):
            for term in terms:
                term = term.lower()
                flipped[term].add(term_id)

    ambisyn = {term: term_ids for term, term_ids in flipped.items() if len(term_ids) > 1}
    return ambisyn


def get_syn_line_terms(path):
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            term_id, terms = line.split(':', 1)
            yield term_id.strip(), [t.strip() for t in terms.split('|') if t.strip()]


def merge_synonyms(input_file, output_file):
    merged_data = defaultdict(set)

    # Step 1: Read and merge data
    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue

            # Split into ID and the synonyms string
            id_part, synonyms_part = line.split(":", 1)
            id_part = id_part.strip()

            # Split synonyms by '|' and add them to the set (removes duplicates)
            synonyms = [s.strip() for s in synonyms_part.split("|") if s.strip()]
            merged_data[id_part].update(synonyms)

    # Step 2: Write the merged data to the output file
    with open(output_file, "w", encoding="utf-8") as f:
        for id_part, synonyms_set in sorted(merged_data.items()):
            # Join synonyms back with '|'
            synonyms_string = "|".join(sorted(synonyms_set))
            f.write(f"{id_part}:{synonyms_string}\n")
