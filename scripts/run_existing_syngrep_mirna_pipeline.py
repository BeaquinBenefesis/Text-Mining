from pipelines.mirna import run_existing_mirna_pipeline
from textmining.config import ExistingSyngrepMirnaConfig
from textmining.paths import OUTPUTS_DIR
from textmining.resources import CORPUS_DIR

if __name__ == '__main__':
    mirna_out = OUTPUTS_DIR / 'mirna'
    config = ExistingSyngrepMirnaConfig(
        output_name='mirna_out',
        hits_path= mirna_out / 'mirna_out.hits',
        synfile_map_path= mirna_out / 'synfile.map',
        synfile_type_map_path= mirna_out / 'synfile_type.map',
        sentence_path = CORPUS_DIR 
    )
    run_existing_mirna_pipeline(config=config)