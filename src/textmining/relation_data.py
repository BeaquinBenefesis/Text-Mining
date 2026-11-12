import csv

import pandas as pd
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split

from textmining.bert import mask_tagged
from textmining.enums import Label

RUNS = '/mnt/raidbio2/extstud/studtemp/mitsopoulos/mirna-annotation'

# training set: two batches labelled by qwen3.5:9b, as (labels, sentences)
QWEN_BATCHES = [
    (f'{RUNS}/runs/qwen35_9b_v5_train13k/full/qwen_out.jsonl', f'{RUNS}/data/sentences_train_13k.tsv'),
    (f'{RUNS}/runs/qwen35_9b_v5_train13k_b/full/qwen_out.jsonl', f'{RUNS}/data/sentences_train_13k_b.tsv'),
]
# test set: 1000 sentences labelled by Claude Opus 5.5
OPUS_TEST = f'{RUNS}/runs/opus_balanced_v06/annotated.tsv'

DEV_SIZE = 0.1
SPLIT_SEED = 0

LABELS = sorted(label.value for label in Label)

# annotation guideline v0.6
_CELL_TISSUE = ['none', 'associated', 'expression_up', 'expression_down', 'expressed']
_PATHWAY_PROCESS = ['none', 'associated', 'promotes', 'inhibits']
ALLOWED_LABELS = {
    'disease': ['none', 'associated', 'expression_up', 'expression_down',
                'biomarker', 'promotes', 'inhibits'],
    'cell': _CELL_TISSUE,
    'tissue': _CELL_TISSUE,
    'gene': ['none', 'associated', 'targets', 'promotes', 'inhibits'],
    'pathway': _PATHWAY_PROCESS,
    'biological_process': _PATHWAY_PROCESS,
}


## LOADING

def prepare(data: pd.DataFrame, mask='all') -> pd.DataFrame:
    """Strip wrapping quotes, add entity_type and optionally mask the entity names.
    mask: False keeps names, True masks the tagged mentions, 'all' also masks their repeats.
    """
    data = data.copy()
    data['sentence'] = data['sentence'].str.replace(r'^"(.*)"$', r'\1', regex=True)

    tags = data['sentence'].str.findall(r'<(\w+)>').map(lambda t: set(t) - {'mir'})
    assert (tags.str.len() == 1).all()
    data['entity_type'] = tags.map(lambda t: next(iter(t)))

    if mask:
        data['sentence'] = data['sentence'].map(lambda s: mask_tagged(s, repeats=mask == 'all'))
    return data


def load_qwen(labels_path: str, sentences_path: str, mask='all') -> pd.DataFrame:
    """One qwen batch: labels from the jsonl, sentences from the tsv."""
    qwen = pd.read_json(labels_path, lines=True, dtype={'sentence_id': str})
    qwen = qwen[qwen['valid']].copy()
    qwen['error'] = qwen['flags'].str.join(',')
    sentences = pd.read_csv(sentences_path, sep='\t', quoting=csv.QUOTE_NONE,
                            dtype=str, usecols=['sentence_id', 'sentence'])
    merged = sentences.merge(qwen[['sentence_id', 'label', 'error']],
                             on='sentence_id', validate='one_to_one')
    return prepare(merged, mask)


def load_train(mask='all') -> pd.DataFrame:
    """Both qwen batches, the first batch first; the batch column holds the batch index."""
    batches = [load_qwen(l, s, mask).assign(batch=i) for i, (l, s) in enumerate(QWEN_BATCHES)]
    train = pd.concat(batches, ignore_index=True)
    assert train['sentence_id'].is_unique
    return train


def load_test(mask='all') -> pd.DataFrame:
    return prepare(pd.read_csv(OPUS_TEST, sep='\t', quoting=csv.QUOTE_NONE,
                               dtype={'sentence_id': str}), mask)


def load_all(mask='all') -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train and test, checked for overlap and against the allowed labels."""
    train, test = load_train(mask), load_test(mask)
    assert not set(train['sentence_id']) & set(test['sentence_id'])
    assert not set(train['sentence']) & set(test['sentence'])
    for data in (train, test):
        assert all(l in ALLOWED_LABELS[t] for t, l in zip(data['entity_type'], data['label']))
    return train, test


def split_dev(train: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fixed, label-stratified split of the training set into (fit, dev)."""
    return train_test_split(train, test_size=DEV_SIZE, stratify=train['label'],
                            random_state=SPLIT_SEED)


## SCORING

def scores(true, predicted) -> dict[str, float]:
    """Accuracy, macro-F1 and the F1 of every label."""
    per_label = f1_score(true, predicted, labels=LABELS, average=None, zero_division=0)
    return {
        'accuracy': accuracy_score(true, predicted),
        'macro_f1': per_label.mean(),
        **{f'f1_{label}': value for label, value in zip(LABELS, per_label)},
    }
