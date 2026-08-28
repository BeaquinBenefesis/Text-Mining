from pathlib import Path
from textmining.analysis import Grouper
from textmining.results_io import read_normalized_hits_tsv
from textmining.paths import OUTPUTS_DIR
from textmining.sentence_utils import SentenceReader
from textmining.resources import SENTENCES_SORTED

norm_path = Path('/mnt/extstudtemp/mitsopoulos/Text-Mining/outputs/mirna/mirna.norm')

def underline(text: str) -> str:
    return f'[{text}]'


def annotate(sentence: str, hit_a, hit_b) -> str:
    spans = sorted(
        [
            (hit_a.start_position, hit_a.start_position + hit_a.hit_length),
            (hit_b.start_position, hit_b.start_position + hit_b.hit_length),
        ]
    )
    pieces = []
    cursor = 0
    for start, end in spans:
        pieces.append(sentence[cursor:start])
        pieces.append(underline(sentence[start:end]))
        cursor = end
    pieces.append(sentence[cursor:])
    return ''.join(pieces)


with SentenceReader(SENTENCES_SORTED) as reader:
    with open(OUTPUTS_DIR / 'co_oc.txt', 'w') as out:
        for sentence_id, hit_a, hit_b in Grouper.extract_cooccurrences(read_normalized_hits_tsv(norm_path)):
            sentence = reader.fetch_text(sentence_id)
            annotated = annotate(sentence, hit_a, hit_b)
            out.write(
                f"{sentence_id}\t{hit_a.normalization.normalized_id}\t{hit_b.normalization.normalized_id}\t{annotated}\n"
            )
