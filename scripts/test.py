from textmining.syngrep import run_syngrep
from textmining.types import HitType
from textmining.resources import MIR_SYNS
from textmining.paths import OUTPUTS_DIR
from pipelines.pipeline import run_existing_pipeline
from textmining.config import MirnaExistingSyngrepPipelineConfig

sentence_pattern = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/corpus/testing/small_test.sent'
syngrep_result = run_syngrep(
        sentence_pattern=sentence_pattern,
        synonyms={HitType.MIR: [MIR_SYNS]},
        output_dir=str(OUTPUTS_DIR / 'small_test'),
        output_name='test',
        no_abbrev_syn_list=[MIR_SYNS],
        abbrev_mode="relaxed",
        ntasks=1,
    )

run_existing_pipeline(
    MirnaExistingSyngrepPipelineConfig(
        output_name='small_test',
        output_dir=OUTPUTS_DIR / 'small_test',
        sentence_path=sentence_pattern,
        syngrep_result=syngrep_result
    )
)