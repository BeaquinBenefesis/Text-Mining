from dataclasses import dataclass
from pathlib import Path
from typing import List
from typing import Generator
from typing import Iterable
from typing import Sequence
from spacy.language import Language
from spacy.tokens import Doc
from spacy.tokens import Span
from tqdm import tqdm
import spacy
import cupy

@dataclass
class Sentence:
    id: str
    text: str

@dataclass
class ProcessedSentence:
    id: str
    text: str
    doc: Doc
    entities: Sequence[Span]

def load_sentences(file_path: str | Path) -> List[Sentence]:
    sentences = []
    with open(file_path, 'r') as f:
        for line in f:
            # Assume format sid \t sentence
            sid, sentence = line.strip().split('\t', maxsplit=1)
            sentences.append(Sentence(sid, sentence))
    return sentences

def process_sentences(file_path: str | Path,
                      nlp: Language,
                      bath_size: int = 64) -> Generator[ProcessedSentence, None, None]:
    sentences = list(load_sentences(file_path))
    out = nlp.pipe(
        ((sentence.text, sentence) for sentence in sentences),
        as_tuples=True,
        batch_size=bath_size
    )

    for doc, sent in out:
        yield ProcessedSentence(sent.id, sent.text, doc, doc.ents)
        

def write_processed_sentences(
    sentences: Iterable[ProcessedSentence],
    output_path: str | Path,
    write_buffer_size: int = 10_000,
):
    buffer = []
    with open(output_path, 'w') as out:
        for sentence in tqdm(sentences, desc="Processing"):
            entities = [e.text for e in sentence.entities]
            labels   = [e.label_ for e in sentence.entities]
            buffer.append(f'{sentence.id}\t{entities}\t{labels}\n')

            if len(buffer) >= write_buffer_size:
                out.writelines(buffer)
                buffer.clear()

        # flush remainder
        if buffer:
            out.writelines(buffer)

if __name__ == '__main__':
    print("Using GPU: ", spacy.prefer_gpu())
    nlp = spacy.load("en_ner_bionlp13cg_md")
    path = "/mnt/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/corpus/chunk_00.sent"
    out = process_sentences(path, nlp, 1024)
    write_processed_sentences(out, "/mnt/extstudtemp/mitsopoulos/Text-Mining/src/NER/out.txt")