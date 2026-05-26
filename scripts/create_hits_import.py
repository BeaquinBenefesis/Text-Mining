from MultiFileReader import MultiFileReader
import argparse
import csv
import os
from typing import Dict


def read_synmap(path: str) -> Dict[str]:
    map = {}
    with open(path, 'r') as m:
        for line in m:
            file_path, num = line.split('\t')
            map[num] = file_path


if __name__ == '__name__':
    parser = argparse.ArgumentParser(description='Read hits file and generate .csv file for neo4j import (outputs relationships from term ids to sentence ids).')
    parser.add_argument()

    parser.add_argument(
        "-hits", metavar="hits", required=True, help="Path to .hits file."
    )

    parser.add_argument(
        "-out", metavar="out", required=True, help="Path to output directory."
    )

    parser.add_argument(
        "-map", metavar='map', required=True, help="Path to synmap file."
    )

    args = parser.parse_args()
    synfile_map = read_synmap(args.map)
    hits_writer = csv.writer(os.path.join(args.out, 'hits.csv'), quoting=csv.QUOTE_ALL)

    with open(os.path.join(args.out, 'hits_header.csv'), 'r') as h:
        h.write(':START_ID,matched_text,start_pos,length,synonym,prefix,suffix,:END_ID,:TYPE')
    
    multiFileReader = MultiFileReader(synfile_map.values())


    with open(args.hits, 'r') as h:
        for line in h:
            parts = line.split('\t')
            if len(parts) != 8:
                raise RuntimeError(f'Illegal line: {line}')
            sent_id = parts[0]
            syn_id = parts[1]
            matched_text = parts[2]
            start_pos = parts[3]
            hit_length = parts[4]
            synonym = parts[5]
            prefix = parts[6]
            suffix = parts[7]

            hits_writer.writerow([syn_id,matched_text,start_pos,hit_length,synonym,prefix,suffix,sent_id,'HIT'])





