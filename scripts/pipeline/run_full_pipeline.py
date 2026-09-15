from pipelines.pipeline import run_pipeline
from textmining.config import CompletePipelineConfig
from textmining.paths import OUTPUTS_DIR

if __name__ == '__main__':
    run_pipeline(CompletePipelineConfig(
        output_name='full_run',
        output_dir= OUTPUTS_DIR / 'full_run',
))
