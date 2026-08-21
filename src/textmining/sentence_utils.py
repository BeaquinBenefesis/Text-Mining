import re

_SENT_ID_RE = re.compile(r'^(?P<article_id>.+)\.(?P<section>\d+)\.(?P<sentence>\d+)$')


def check_sorted(sent_id_a, sent_id_b) -> bool:
    article_a, section_a, num_a = parse_sentence_id(sent_id_a)
    article_b, section_b, num_b = parse_sentence_id(sent_id_b)

    if article_a != article_b:
        return True
        
    return (section_a, num_a) <= (section_b, num_b)

def parse_sentence_id(sentence_id: str) -> tuple[str, int, int]:
    match = _SENT_ID_RE.match(sentence_id)
    if not match:
        raise ValueError(f"Unrecognized sentence_id format: {sentence_id!r}")
    return (
        match.group('article_id'),
        int(match.group('section')),
        int(match.group('sentence')),
        )


class SentenceReader:

    def __init__(self, sentence_path):
        self._file = open(sentence_path, 'r')
        self._current_sent_id = None
        self._current_text = None
        self._exhausted = False


    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc, tb):
        self.close()



    def _advance(self):
        for line in self._file:
            line = line.rstrip('\n')
            if not line:
                continue
            sent_id, text = line.split('\t', 1)
            self._current_sent_id = sent_id
            self._current_text = text
            return
        
        self._exhausted = True
        self._current_sent_id = None
        self._current_text = None

    def fetch_text(self, sent_id):
        while self._current_sent_id != sent_id:
            if self._exhausted:
                raise ValueError(f'Sentence stream exhausted! Could not find sentence with id {sent_id} in {self._file.name}')
            if self._current_sent_id and not check_sorted(self._current_sent_id, sent_id):
                raise ValueError(f'Sentence pointer passed requested sentence id!')
            self._advance()
        return self._current_text

    def close(self):
        self._file.close()
