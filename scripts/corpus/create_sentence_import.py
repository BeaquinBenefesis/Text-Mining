import argparse
import os
import csv

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Parses sentence files and generate corresponding .csv files for neo4j import.'
    )
    parser.add_argument('-sent', metavar='sent', required=True, help='Path to sentence file.')
    parser.add_argument('-out', metavar='out', required=True, help='Path to output directory.')
    
    args = parser.parse_args()
    sent = args.sent
    out = args.out

    with open(sent, 'r') as f, \
        open(os.path.join(out, 'sentence_header.csv'), 'w') as sent_header, \
        open(os.path.join(out, 'section_header.csv'), 'w') as section_header, \
        open(os.path.join(out, 'article_header.csv'), 'w') as article_header, \
        open(os.path.join(out, 'sentence_structure_header.csv'), 'w') as edges:
        sent_header.write('sentenceId:ID,text,:LABEL\n')
        section_header.write('sectionId:ID,:LABEL\n')
        article_header.write('articleId:ID,:LABEL\n')
        edges.write(':START_ID,:END_ID,:TYPE\n')

    with open(sent, 'r') as f, \
        open(os.path.join(out, 'sentences.csv'), 'w') as sent_out, \
        open(os.path.join(out, 'sections.csv'), 'w') as section_out, \
        open(os.path.join(out, 'articles.csv'), 'w') as article_out, \
        open(os.path.join(out, 'structure.csv'), 'w') as edges_out:


        sent_writer = csv.writer(sent_out, quoting=csv.QUOTE_ALL)
        section_writer = csv.writer(section_out, quoting=csv.QUOTE_ALL)
        article_writer = csv.writer(article_out, quoting=csv.QUOTE_ALL)
        edges_writer = csv.writer(edges_out, quoting=csv.QUOTE_ALL)

        prev_article_id = ''
        prev_section_id = ''

        for i, line in enumerate(f):
            if (i % 100000 == 0):
                print(i, 'sentences processed')
            sent_id, text = line.split('\t')
            text = text.replace('\n', '')
            article_id, section_num, sentence_num = sent_id.split('.')
            section_id = '.'.join([article_id, section_num])
            
            if prev_article_id != article_id:
                article_writer.writerow([article_id,'ARTICLE'])
                prev_article_id = article_id
            if prev_section_id != section_id:
                section_writer.writerow([section_id,'SECTION'])
                prev_section_id = section_id
                edges_writer.writerow([section_id,article_id,'IN_ARTICLE'])

            sent_writer.writerow([sent_id,text,'SENTENCE'])
            edges_writer.writerow([sent_id,section_id,'IN_SECTION'])