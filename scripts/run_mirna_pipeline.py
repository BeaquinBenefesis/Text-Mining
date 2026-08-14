from pipelines.mirna import run_mirna_pipeline
from textmining.resources import CORPUS_SAMPLE

if __name__ == '__main__':
    print(f'Running on {CORPUS_SAMPLE}')
    run_mirna_pipeline('mirna_out', sentence_path=CORPUS_SAMPLE)