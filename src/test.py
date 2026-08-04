from syngrep import run_syngrep
from models import HitType

disease_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/disease.syn'
disease_abbrev_path = '/mnt/extstudtemp/mitsopoulos/Text-Mining/disease_abbreviations.txt'
sentences = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/validation/disease/NCBI_disease/processed_text/NCBItestset_corpus.sent'
synonyms = {HitType.DISEASE: [disease_path]}
abbrevs = {HitType.DISEASE: [disease_abbrev_path]}
output_dir = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/validation/disease/NCBI_disease/out_hits_test_1'
output_name = 'output'
model_hits = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/validation/disease/NCBI_disease/model_hits/NCBItestset_corpus.hits'
mapping = '/mnt/extstudtemp/mitsopoulos/Text-Mining/disease_mapping.json'

res = run_syngrep(sentence_pattern=sentences,
            synonyms=synonyms,
            abbrev_synonyms=abbrevs,
            output_dir=output_dir,
            output_name=output_name,
            abbrev=False)