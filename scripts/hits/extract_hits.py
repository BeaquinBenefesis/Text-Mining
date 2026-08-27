import argparse
import glob
import os


def extract_article_ids(hits_files):
    article_ids = set()
    for hits_file in hits_files:
        with open(hits_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                columns = line.split("\t")
                if len(columns) < 1:
                    continue
                
                article, sentence_id = columns[0].split(':')
                article_id = sentence_id.split(".")[0]  # extract PMC176545 or PMID_001
                article_ids.add(article_id)
    
    return article_ids


def extract_sentences(sent_dir, article_ids, output_file):
    with open(output_file, "w") as out:
        for sent_file in glob.glob(f"{sent_dir}/*.sent"):
            print(f"Scanning {os.path.basename(sent_file)}...")
            with open(sent_file) as f:
                for line in f:
                    if not line.strip():
                        continue
                    sentence_id = line.split('\t')[0]
                    article_id = sentence_id.split('.')[0]

                    if article_id in article_ids:
                        out.write(line)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
)

    parser.add_argument('-hits', nargs='+', required=True, help='Path to one or more hit files')
    parser.add_argument("-sent", metavar="sent", required=True, help="Path to sentences dir.")
    parser.add_argument("-out", metavar="out", required=True, help="Output file.")

    args = parser.parse_args()
    hits = args.hits
    sent = args.sent
    out = args.out

    print("Extracting article ids from hits list...")
    article_ids = extract_article_ids(hits)
    print("Done!")
    print("Starting sentence extraction...")
    extract_sentences(sent, article_ids, out)