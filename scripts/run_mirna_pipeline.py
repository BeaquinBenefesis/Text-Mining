from pipelines.pipeline import run_pipeline
from textmining.config import MirnaPipelineConfig
from textmining.paths import OUTPUTS_DIR

if __name__ == '__main__':
    run_pipeline(MirnaPipelineConfig(
        output_name='mirna',
        output_dir=OUTPUTS_DIR / 'mirna',
    ))