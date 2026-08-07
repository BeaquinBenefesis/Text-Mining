from textmining.syngrep import run_syngrep
from textmining.models import HitType
from textmining.hit_utils import HitsProcessor
from textmining.ontology import OntologyGraph
from textmining.normalization import DefaultNormalizer
from textmining.core import Processor
from textmining.scoring import HitScorer
from textmining.article_utils import ArticleRecord

disease_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/disease.syn'
disease_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/disease.syn'
disease_abbrev_path = '/mnt/extstudtemp/mitsopoulos/Text-Mining/disease_abbreviations.txt'
sentences = '/mnt/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/corpus/*.sent'
synonyms = {HitType.DISEASE: [disease_path]}
abbrevs = {HitType.DISEASE: [disease_abbrev_path]}
output_dir = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/new_disease_run'
output_name = 'output'
worchar = '.,'

MONDO_OBO_PATH = "/mnt/raidbio2/extstud/studtemp/mitsopoulos/ontologies/diseases/mondo_disease_ontology.obo"

disease_graph = OntologyGraph.from_obo(MONDO_OBO_PATH)
type_to_ontology = {HitType.DISEASE: disease_graph}

res = run_syngrep(ntasks=50,
            sentence_pattern=sentences,
            synonyms=synonyms,
            abbrev_synonyms=abbrevs,
            output_dir=output_dir,
            output_name=output_name,
            abbrev=True, word_char=worchar)

hits_processor = HitsProcessor(hits_path=res.hits_path, synfile_map=res.synfile_map_path, synfile_type_map=res.synfile_type_map_path, type_to_ontology=type_to_ontology)
default_normalizer = DefaultNormalizer()
normalizers = {
    HitType.DISEASE: default_normalizer
}
scorer = HitScorer(type_to_ontology=type_to_ontology)

main_processor = Processor(hits_processor=hits_processor,
                           normalizers=normalizers,
                           scorer=scorer)

with open('normalized_output.tsv', 'w') as out:
    for article in main_processor.get_normalized_article_stream():
        for h in article.normalized_hits:
            out.write(f'{h.sentence_id}\t{h.raw_text}\t{h.start_position}\t{h.hit_length}\t{h.normalization.normalized_id}\t{h.score}')
