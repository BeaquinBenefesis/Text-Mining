import json
import re
from collections.abc import Iterable, Iterator
from itertools import islice
from pathlib import Path
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from textmining.enums import HitType
from textmining.resources import PUBMEDBERT_DIR
from textmining.web.highlight import extend_mirna_span
from textmining.enums import Label

Span = tuple[int, int, str]

_WS = re.compile(r"\s+")
_TAG = re.compile(r"<(\w+)>(.*?)</\1>")
MAX_LEN = 320

## SPANS

def pair_spans(text: str, mirna_span: tuple[int, int], term_span: tuple[int, int],
               term_type: HitType) -> list[Span]:
    """The two spans of a co-occurrence, the miRNA one extended to the full name."""
    return [(*extend_mirna_span(text, *mirna_span), HitType.MIR.value),
            (*term_span, term_type.value)]


def valid_spans(text: str, spans: list[Span]) -> bool:
    """True if all spans lie inside the text and none overlap."""
    spans = sorted(spans)
    in_range = all(0 <= s < e <= len(text) for s, e, _ in spans)
    return in_range and all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))


def substitute(text: str, spans: list[Span], fmt) -> str:
    """Replace each (start, end, entity_type) span with fmt(surface, entity_type)."""
    for start, end, kind in sorted(spans, reverse=True):
        text = text[:start] + fmt(text[start:end], kind) + text[end:]
    return _WS.sub(" ", text).strip()


def masked(surface: str, kind: str) -> str:
    return f"${kind}"


def tagged(surface: str, kind: str) -> str:
    tag = kind.lower()
    return f"<{tag}>{surface}</{tag}>"


def untag(sentence: str) -> tuple[str, list[Span]]:
    """Split a tagged sentence into its plain text and the spans of the tagged mentions."""
    text, spans, cursor = "", [], 0
    for match in _TAG.finditer(sentence):
        text += sentence[cursor:match.start()]
        spans.append((len(text), len(text) + len(match.group(2)), match.group(1).upper()))
        text += match.group(2)
        cursor = match.end()
    return text + sentence[cursor:], spans


## MASKING

def mask_names(text: str, spans: list[Span], repeats: bool = True) -> str:
    """Replace the mentions at spans with $TYPE; with repeats, also every repeat of their names."""
    names = [(_WS.sub(" ", text[start:end]), kind) for start, end, kind in spans]
    text = substitute(text, spans, masked)
    if not repeats:
        return text
    # longer name first, in case one name is part of the other
    for name, kind in sorted(names, key=lambda n: -len(n[0])):
        if len(name) < 2:
            continue                  # a one-letter "name" would also hit ordinary words
        # whole names only ("miR-21" must not match inside "miR-214" or "$MIR"),
        # with an optional plural s
        pattern = r"(?<![\w$])" + re.escape(name) + r"s?(?!\w)"
        # short names like "AS" or "AD" must match exactly, or "as" and "ad" are hit too
        flags = re.IGNORECASE if len(name) > 3 else 0
        text = re.sub(pattern, lambda m: masked(m.group(), kind), text, flags=flags)
    return text


def mask_tagged(sentence: str, repeats: bool = True) -> str:
    """mask_names for a sentence whose two mentions are marked as <type>mention</type>."""
    return mask_names(*untag(sentence), repeats=repeats)


## MODEL INPUT

def tokenize(tokenizer, entity_type: str, sentence: str, max_len: int = MAX_LEN):
    """Token IDs of one instance: the entity type as words, then the masked sentence."""
    return tokenizer(entity_type.lower().replace("_", " "), sentence,
                     truncation="only_second", max_length=max_len)


def allowed_masks(allowed_labels: dict[str, list[str]], labels: list[str]) -> dict[str, torch.Tensor]:
    """Per entity type, which positions of labels are allowed for that type."""
    return {entity_type: torch.tensor([label in allowed for label in labels])
            for entity_type, allowed in allowed_labels.items()}


def masked_logits(model, batch, mask: torch.Tensor) -> torch.Tensor:
    """Run the model on one batch and block the labels that are not allowed."""
    batch = {key: values.to(model.device) for key, values in batch.items()}
    logits = model(**batch).logits               # one score per label, per instance
    return logits.masked_fill(~mask.to(model.device), -1e4)


## ANNOTATOR

class RelationAnnotator:
    """Labels miRNA-term co-occurrences with the fine-tuned PubMedBERT."""

    def __init__(self, model_dir: Path = PUBMEDBERT_DIR, device: str | None = None,
                 batch_size: int = 64, chunk_size: int = 10_000):
        settings = json.loads((model_dir / "settings.json").read_text())
        if settings["mask_entities"] != "all":
            raise ValueError(f"model was trained with mask_entities={settings['mask_entities']!r}, expected 'all'")
        device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_dir).to(device).eval()
        self.labels = [Label(self.model.config.id2label[i]) for i in range(self.model.config.num_labels)]
        self.allowed = allowed_masks(settings["allowed_labels"], self.labels)
        self.max_len = settings["max_len"]
        self.batch_size = batch_size      # co-occurrences per model call
        self.chunk_size = chunk_size      # co-occurrences read, sorted by length and labelled together

    def model_input(self, text: str, mirna_span: tuple[int, int], term_span: tuple[int, int], term_type: HitType):
        """Token IDs and allowed labels of one co-occurrence; None if it cannot be labelled."""
        spans = pair_spans(text, mirna_span, term_span, term_type)
        allowed = self.allowed.get(term_type.value.lower())
        # a term type the model was not trained on, or mentions that overlap
        if allowed is None or not valid_spans(text, spans):
            return None
        return tokenize(self.tokenizer, term_type.value, mask_names(text, spans), self.max_len), allowed

    def annotate(self, cooccurrences: Iterable[tuple]) -> Iterator[dict[Label, float] | None]:
        """The probability of every label for each (text, mirna_span, term_span, term_type), in input order.
        None for a co-occurrence that cannot be labelled.
        Outputs: A dictionary from label to probability {none: 0.78, associated: 0.12, ...}
        """
        cooccurrences = iter(cooccurrences)
        while chunk := list(islice(cooccurrences, self.chunk_size)):
            yield from self._annotate_chunk(chunk)

    @torch.no_grad()
    def _annotate_chunk(self, cooccurrences: list[tuple]) -> list[dict[Label, float] | None]:
        inputs = [self.model_input(*cooccurrence) for cooccurrence in cooccurrences]
        usable = [i for i, model_input in enumerate(inputs) if model_input is not None]
        usable.sort(key=lambda i: len(inputs[i][0]["input_ids"]))   # similar lengths together: less padding
        on_gpu = self.model.device.type == "cuda"
        results = [None] * len(inputs)
        for start in range(0, len(usable), self.batch_size):
            batch_ids = usable[start:start + self.batch_size]
            batch = self.tokenizer.pad([inputs[i][0] for i in batch_ids], return_tensors="pt")
            mask = torch.stack([inputs[i][1] for i in batch_ids])
            with torch.autocast("cuda", dtype=torch.float16, enabled=on_gpu):   # half precision: faster
                logits = masked_logits(self.model, batch, mask)
            probabilities = logits.float().softmax(dim=-1)
            for i, row in zip(batch_ids, probabilities.tolist()):
                results[i] = dict(zip(self.labels, row))
        return results
