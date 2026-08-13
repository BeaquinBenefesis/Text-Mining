from pipelines.disease import run_existing_disease_pipeline
from textmining.config import ExistingSyngrepDiseaseConfig
from textmining.paths import OUTPUTS_DIR


if __name__ == '__main__':
    disease_output = OUTPUTS_DIR / 'disease'
    config = ExistingSyngrepDiseaseConfig(
        output_name='disease_run',
        hits_path=disease_output / 'disease_run.hits',
        synfile_map_path=disease_output / 'synfile.map',
        synfile_type_map_path=disease_output / 'synfile_type.map'
    )
    run_existing_disease_pipeline(config=config)