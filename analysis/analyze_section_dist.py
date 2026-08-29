import numpy as np
import textmining.sentence_utils as sent

paths = []
pmc_section_num = np.array(dtype=np.int8)
pubmed_section_num = np.array(dtype=np.int8)


for path in paths:
    with open(path, 'r') as f:
        prev_article_id = None
        for line in f:
            sent_id = line.split('\t', 1)[0]
            article_id, section_num, sentence_num = sent.parse_sentence_id(sent_id)
            if prev_article_id and prev_article_id != article_id:
                if article_id.startswith('PMC'):
                    pmc_section_num.append(section_num)
                else:
                    pubmed_section_num.append(section_num)
            prev_article_id = article_id
            