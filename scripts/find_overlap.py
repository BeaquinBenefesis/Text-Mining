import pandas as pd
from itertools import groupby
from python.src.NER.hitsUtils import HitsProcessor

results = []
current_rows = []
current_id = None
processed = 0

with open('/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/linnaeus_hits/sorted.hits', 'r') as f:
    for line in f:
        parts = line.strip().split('\t')
        sent_id = parts[0].split(':')[1]
        start = int(parts[3])
        length = int(parts[4])
        matched_text = parts[2]

        if sent_id != current_id:
            # Process previous group
            if current_rows:
                intervals = [(r[0], r[0] + r[1], r[2]) for r in current_rows]
                for i in range(len(intervals)):
                    for j in range(i + 1, len(intervals)):
                        s1, e1, t1 = intervals[i]
                        s2, e2, t2 = intervals[j]
                        if s1 < e2 and s2 < e1:
                            results.append((current_id, t1, t2, s1, e1, s2, e2))
                processed += 1
                if processed % 10000 == 0:
                    print(f"Processed {processed} sentences, {len(results)} overlaps found so far")

            current_id = sent_id
            current_rows = []

        current_rows.append((start, length, matched_text))

# Don't forget the last group
if current_rows:
    intervals = [(r[0], r[0] + r[1], r[2]) for r in current_rows]
    for i in range(len(intervals)):
        for j in range(i + 1, len(intervals)):
            s1, e1, t1 = intervals[i]
            s2, e2, t2 = intervals[j]
            if s1 < e2 and s2 < e1:
                results.append((current_id, t1, t2, s1, e1, s2, e2))

overlaps = pd.DataFrame(results, columns=['sentence_id', 'matched_text_i', 'matched_text_j', 'start_i', 'end_i', 'start_j', 'end_j'])
print(f"Done! Found {len(overlaps)} overlapping pairs")
overlaps.to_csv('/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/overlaps.csv', index=False)