from pipelines.everything import run_complete_pipeline
from textmining.resources import CORPUS_SAMPLE


if __name__ == '__main__':
    run_complete_pipeline('everything_run', sentence_path=CORPUS_SAMPLE)