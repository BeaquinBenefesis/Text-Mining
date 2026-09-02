"""Run syngrep + HitProcessing + Normalization over MIR_TEST_SENTS and report
what fraction of the guaranteed miRNA entities (one per line) get detected
and successfully normalized."""
from collections import Counter
from textmining.syngrep import run_syngrep
from textmining.enums import HitType
from textmining import resources as res
from textmining.paths import OUTPUTS_DIR
from textmining.config import MirnaPipelineConfig
from textmining.sentence_utils import parse_sentence_id
from textmining.results_io import read_normalized_hits_tsv
from textmining.normalization import normalized_successfully
from pipelines.pipeline import run_existing_pipeline, run_pipeline
import logging

OUTPUT_NAME = 'mir_test_sents'
OUTPUT_DIR = OUTPUTS_DIR / OUTPUT_NAME


def main():
    run_pipeline(
        MirnaPipelineConfig(output_name=OUTPUT_NAME,
                            output_dir=OUTPUT_DIR,
                            n_tasks=1,
                            sentence_pattern=str(res.MIR_TEST_SENTS)),
        debug=logging.DEBUG
    )

    sentence_categories: dict[str, str] = {}
    sentence_texts: dict[str, str] = {}
    with res.MIR_TEST_SENTS.open() as fh:
        for line in fh:
            line = line.rstrip('\n')
            if not line:
                continue
            sent_id, text = line.split('\t', 1)
            category, _, _ = parse_sentence_id(sent_id)
            sentence_categories[sent_id] = category
            sentence_texts[sent_id] = text

    detected = set()
    normalized = set()
    not_normalized_hits = []
    for hit in read_normalized_hits_tsv(OUTPUT_DIR / f'{OUTPUT_NAME}.norm'):
        if hit.entity_type != HitType.MIR or hit.sentence_id not in sentence_categories:
            continue
        detected.add(hit.sentence_id)
        if normalized_successfully(hit):
            normalized.add(hit.sentence_id)
        else:
            not_normalized_hits.append(hit)

    all_ids = set(sentence_categories)
    total = len(all_ids)
    print(f'Total test sentences: {total}')
    print(f'Detected (>=1 MIR hit): {len(detected)} ({len(detected) / total:.2%})')
    print(f'Normalized successfully: {len(normalized)} ({len(normalized) / total:.2%})')
    print(f'Missing entirely: {total - len(detected)}')

    category_totals = Counter(sentence_categories.values())
    print('\nBy category:')
    for category, cat_total in sorted(category_totals.items()):
        cat_ids = {sid for sid, cat in sentence_categories.items() if cat == category}
        cat_detected = detected & cat_ids
        cat_normalized = normalized & cat_ids
        print(f'  {category}: total={cat_total}, '
              f'detected={len(cat_detected)} ({len(cat_detected) / cat_total:.2%}), '
              f'normalized={len(cat_normalized)} ({len(cat_normalized) / cat_total:.2%})')

    missed_path = OUTPUT_DIR / f'{OUTPUT_NAME}_missed.sent'
    not_normalized_path = OUTPUT_DIR / f'{OUTPUT_NAME}_not_normalized.txt'
    missed_ids = sorted(all_ids - detected, key=lambda sid: (sentence_categories[sid], sid))
    with missed_path.open('w') as fh:
        for sent_id in missed_ids:
            fh.write(f'{sent_id}\t{sentence_texts[sent_id]}\n')
    print(f'\nWrote {len(missed_ids)} missed sentences to {missed_path}')

    not_normalized_hits.sort(key=lambda hit: (sentence_categories.get(hit.sentence_id, ''), hit.sentence_id))
    with not_normalized_path.open('w') as fh:
        fh.write('sentence_id\ttext\traw_text\tprefix\tsuffix\tentity_id\tnorm_status\n')
        for hit in not_normalized_hits:
            status = hit.normalization.status.name if hit.normalization and hit.normalization.status else ''
            fh.write(f'{hit.sentence_id}\t{sentence_texts.get(hit.sentence_id, "")}\t{hit.raw_text}\t'
                     f'{hit.prefix or ""}\t{hit.suffix or ""}\t{hit.entity_id}\t{status}\n')
    print(f'Wrote {len(not_normalized_hits)} not-normalized hits to {not_normalized_path}')


if __name__ == '__main__':
    main()
