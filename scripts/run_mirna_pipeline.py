from pipelines.mirna import run_mirna_pipeline
from textmining.resources import CORPUS_DIR

if __name__ == '__main__':
    run_mirna_pipeline('mirna_out', sentence_path=CORPUS_DIR)