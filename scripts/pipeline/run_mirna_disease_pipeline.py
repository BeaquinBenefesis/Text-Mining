from pipelines.pipeline import run_pipeline
from textmining.config import MirnaDiseasePipelineConfig
from textmining.paths import OUTPUTS_DIR
from textmining.resources import CORPUS_SAMPLE_SMALLER

if __name__ == '__main__':
    run_pipeline(MirnaDiseasePipelineConfig(
        output_name='mirna_and_disease',
        output_dir= OUTPUTS_DIR / 'mirna_and_disease'
))