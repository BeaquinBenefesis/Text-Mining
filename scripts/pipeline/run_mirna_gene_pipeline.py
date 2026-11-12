from pipelines.pipeline import run_pipeline
from textmining.config import MirnaGenePipelineConfig
from textmining.paths import OUTPUTS_DIR
from textmining.resources import CORPUS_SAMPLE_SMALLER

if __name__ == '__main__':
    run_pipeline(MirnaGenePipelineConfig(
        sentence_pattern=str(CORPUS_SAMPLE_SMALLER),
        output_name='mirna_gene',
        output_dir=OUTPUTS_DIR / 'mirna_gene',
    ))
