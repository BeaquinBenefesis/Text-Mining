import re
import pandas as pd
from hitsUtils import get_hits_df

class MirProcessor:

    def __init__(self, mirna_hits_path, mirna_syn_path, prefix_regex_path):
        print('Reading mirna hits...')
        self.mirna_hits = get_hits_df(mirna_hits_path, mirna_syn_path)
        with open(prefix_regex_path, 'r') as r:
            prefix_pattern = r.readline()
            print(f'Prefix pattern: {prefix_pattern}')
            self.prefix_regex = f"((?:{prefix_pattern}))[-‐ ]$"

    def verify_bantam_context(self, sentence):
        # High-confidence positive biological anchors
        pos_anchors = r'mir|miRNA|microRNA|micro-RNA|micro-RNAs|gene|locus|target|drosophila|flies|dme-'
        # Negative non-biological anchors
        neg_anchors = r'bantamweight|chick|hen|rooster|poultry|fowl|duck|breed|books|publisher|paperback|fiction'
        
        if re.search(neg_anchors, sentence, re.IGNORECASE):
            return "FILTER_OUT" # Found poultry or publishing context
        elif re.search(pos_anchors, sentence, re.IGNORECASE):
            return "KEEP_MIRNA" # Confirmed molecular biology context
        else:
            return "AMBIGUOUS" # Flag for manual inspection
        

    def normalize_mirna_prefix(self):
        # Everything to lowercase
        print('miRNA prefix normalization started...')
        self.mirna_hits['prefix'] = self.mirna_hits['prefix'].str.lower()
        extracted = self.mirna_hits['prefix'].str.extract(self.prefix_regex, expand=False)
        print(f"Total prefixes found: {self.mirna_hits['prefix'].notna().sum()}, valid prefixes found: {extracted.notna().sum()}")
        self.mirna_hits['prefix'] = extracted
        #self.mirna_hits.to_csv('/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/normalized_pre.tsv', sep='\t', index=False)
    

    def normalize_mirna_suffix(self):
        print('miRNA suffix normalization started...')

        # Leading separator: -, _, or x
        leading = r"[-_x]?"

        # Optional letter prefix before the first number (BART, HSUR, iab, K...)
        let_prefix = r"[a-zA-Z]{0,5}"

        # Required number
        number = r"[0-9]+"

        # Optional trailing letters+digits after a number (a, RC, b2...)
        let_suffix  = r"(?:[a-zA-Z]{1,2}[0-9]*)*"

        # One full segment
        segment =  rf"(?:{let_prefix}{number}{let_suffix})"

        # Additional segments, but not if the next thing is a strand marker
        more_segs = rf"(?:[-_](?![35][pP]){segment})*"

        # Strand marker
        strand = r"(\*|[-/]?[35][pP])?"

        # Assembled
        group1 = rf"({leading}{segment}{more_segs})"
        pattern = rf"^{group1}{strand}"
        
        
        extracted = self.mirna_hits['suffix'].str.extract(pattern, expand=True)
        self.mirna_hits['matched_suffix'] = extracted[0]
        self.mirna_hits['mature_mirna_suffix'] = extracted[1]
        self.mirna_hits[self.mirna_hits['matched_suffix'].notna()].to_csv('/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/normalized_suffix.tsv', sep='\t', index=False)


if __name__ == '__main__':
    hits = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/mir_hits_new/mir_hits_20260612_190239.hits'
    regex_pattern = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/prefix_regex.txt'
    processor = MirProcessor(hits, regex_pattern)
    #processor.normalize_mirna_prefix()
    processor.normalize_mirna_suffix()
    #pattern = r"^((?:[-_x]?)(?:(?:[a-zA-Z]{1,4})?[-_x]?[0-9]+(?:[a-zA-Z]{1,2}[0-9]*)?))(\*|[-/]?[35][pP])?"
    #test = pd.Series(['-related', '-BART10-5p', '-mir-H3', '-K12-10a-3p'])
    #result = test.str.extract(pattern, expand=True)
    #result.columns = ['matched_suffix', 'mature_mirna_suffix']
    #print(result)    