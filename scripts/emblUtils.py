import re
import pandas as pd

def parse_mirbase_embl(filepath) -> pd.DataFrame:
    records = []
    current = {}
    
    with open(filepath, 'r') as f:
        for line in f:
            if line.startswith('ID'):
                # ID line: first token after 'ID' is the miRNA name
                current['name'] = line.split()[1]
            elif line.startswith('AC'):
                # AC line: accession like MI0000001;
                ac = line.split()[1].rstrip(';')
                current['accession'] = ac
            elif line.startswith('//'):
                # End of record
                if 'name' in current and 'accession' in current:
                    records.append(current)
                current = {}
    
    return pd.DataFrame(records, columns=['name', 'accession'])