from pipelines.pipeline import run_pipeline
from textmining.config import MirnaDiseasePipelineConfig
from textmining.paths import OUTPUTS_DIR
from textmining.resources import HMDD_SENTS

if __name__ == '__main__':
    run_pipeline(MirnaDiseasePipelineConfig(
        output_name='hmdd_sents',
        output_dir= OUTPUTS_DIR / 'hmdd_sents',
        sentence_pattern=str(HMDD_SENTS)
))
