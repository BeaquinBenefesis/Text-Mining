from pipelines.pipeline import run_from_normalized_output
from textmining.paths import OUTPUTS_DIR

if __name__ == '__main__':
    name = 'mirna_and_disease'
    output_dir = OUTPUTS_DIR / name
    run_from_normalized_output(
        norm_hits_pattern=str(output_dir / f'{name}.norm'),
        output_name=name,
        output_dir=output_dir,
        duck=False
    )