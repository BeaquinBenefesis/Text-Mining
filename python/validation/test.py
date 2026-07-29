from bioc import pubtator

corpus_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/validation/disease/NCBI_disease/raw/NCBItestset_corpus.txt'
name_out = 'NCBItestset_corpus'
sentences = f'/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/validation/disease/NCBI_disease/processed_text/{name_out}.sent'
annotations_path = f'/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/validation/disease/NCBI_disease/model_hits/{name_out}.hits'

with open(corpus_path, "r", encoding="utf-8") as f:
    documents = pubtator.load(f)

seen_docs = set()
with open(sentences, 'w') as sent_out, \
    open(annotations_path, 'w') as hits_out:
    for doc in documents:
        id = f'{doc.pmid}.1.1'
        text = doc.text
        text = text.replace('\n', ' ')
        if id in seen_docs:
            continue
        seen_docs.add(id)
        sent_out.write(f'{id}\t{text}\n')
        
        # Write hits
        for ann in doc.annotations:
            hits_out.write(f'{id}\t{ann.id}\t{ann.text}\t{ann.start}\t{ann.end-ann.start}\t{ann.type}\n')
        