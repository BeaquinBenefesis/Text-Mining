from textmining.syngrep import run_syngrep
import textmining.resources as resources
from textmining.types import HitType
from textmining.paths import OUTPUTS_DIR
from textmining.hit_utils import HitProcessor
from textmining.ontology import OntologyGraph
from textmining.config import MirbaseResources
from textmining.mirbase import load_mirbase
from textmining.article_utils import ArticleSource
from textmining.analysis import Grouper
from textmining.sentence_utils import SentenceReader
from textmining.core import Processor
from textmining.normalization_resources import MirResourceLoader
from collections import defaultdict
from itertools import combinations
import spacy
import csv
from textmining.normalization import DefaultNormalizer, MirNormalizer
from textmining.scoring import HitScorer
from textmining.types import NormalizationStatus


def sample_distances(article_stream, sentence_reader, nlp, output_path, use_normalized):
        sentence_to_hit_pair = defaultdict(tuple)
        id_sentence_pairs = []
        sent_id_to_text = {}
        for article in article_stream:
            article_hits = []
            if use_normalized:
                article_hits = [h for h in article.normalized_hits if h.normalization.status in {NormalizationStatus.NORMALIZED, NormalizationStatus.FALLBACK}]
            else:
                article_hits = article.resolved_hits
            for sentence_id, sentence_hits in Grouper.group_by_sentence(article_hits):
                if len(sentence_hits) != 2:
                    continue
                sentence_text = sentence_reader.fetch_text(sentence_id)
                for (hit_a, hit_b) in combinations(sentence_hits, 2):
                    type_a = hit_a.entity_type
                    type_b = hit_b.entity_type
                    
                    if not Grouper.valid_types(type_a, type_b) or not HitType.DISEASE in {type_a, type_b}:
                        continue
                    if Grouper.overlapping_pair(hit_a, hit_b):
                        continue
                    
                    sentence_to_hit_pair[sentence_id] = (hit_a, hit_b)
                    id_sentence_pairs.append((sentence_text, sentence_id))
                    sent_id_to_text[sentence_id] = sentence_text
        
        
        with open(output_path, 'w') as out:
            out.write(f'sentence_id\thit_a\thit_b\tdistance\ttext\n')
            for doc, sentence_id in nlp.pipe(id_sentence_pairs, as_tuples=True, batch_size=1000):
                hit_a, hit_b = sentence_to_hit_pair[sentence_id]
                start_a = hit_a.start_position
                start_b = hit_b.start_position
                end_a = start_a + hit_a.hit_length
                end_b = start_b + hit_b.hit_length
                sentence_text = sent_id_to_text[sentence_id]
                
                hit_a_span = doc.char_span(start_a, end_a, alignment_mode="expand")
                hit_b_span = doc.char_span(start_b, end_b, alignment_mode="expand")
                
                if hit_a_span is None or hit_b_span is None:
                    print(f'Skipped: {hit_a.to_dict(), hit_b.to_dict()}')
                    continue
                
                first, second = sorted([hit_a_span, hit_b_span], key=lambda s: s.start)
                distance = max(0, second.start - first.end)
                out.write(f'{sentence_id}\t{hit_a.raw_text}\t{hit_b.raw_text}\t{distance}\t{sentence_text}\n')

if __name__ == '__main__':
    
    res_hmdd = run_syngrep(
        output_dir=OUTPUTS_DIR / 'HMDD',
        sentence_pattern=str(resources.HMDD_SENTS),
        synonyms={
            HitType.MIR: [resources.MIR_SYNS],
            HitType.DISEASE: [resources.DISEASE_SYNS]
        },
        within_word=[resources.MIR_SYNS.name],
    )
    res_background = run_syngrep(
        output_dir= OUTPUTS_DIR / 'disease_and_mir',
        sentence_pattern=str(resources.CORPUS_SAMPLE),
        synonyms={
            HitType.MIR: [resources.MIR_SYNS],
            HitType.DISEASE: [resources.DISEASE_SYNS]
        },
        within_word=[resources.MIR_SYNS.name],
    )

    disease_graph = OntologyGraph.from_obo(resources.MONDO_OBO, exclude_gci=True)
    mirna_graph = OntologyGraph.from_dict(*load_mirbase(
        families_tsv=MirbaseResources.families_path,
        precursors_tsv=MirbaseResources.precursor_path,
        mature_tsv=MirbaseResources.mature_path,
        parent_to_child_tsv=MirbaseResources.parent_to_child_path
    ))
    type_to_onto = {
        HitType.MIR: mirna_graph,
        HitType.DISEASE: disease_graph
    }
    
    processor_hmdd = HitProcessor(
        hits_path=res_hmdd.hits_path,
        synfile_map=res_hmdd.synfile_map_path,
        synfile_type_map=res_hmdd.synfile_type_map_path,
        type_to_ontology=type_to_onto,
    )
    processor_bg = HitProcessor(
        hits_path=res_background.hits_path,
        synfile_map=res_background.synfile_map_path,
        synfile_type_map=res_hmdd.synfile_type_map_path,
        type_to_ontology=type_to_onto,
    )
    sentence_reader_hmdd = SentenceReader(resources.HMDD_SENTS)
    sentence_reader_bg = SentenceReader(resources.CORPUS_SAMPLE)
    nlp = spacy.load("en_core_sci_sm", exclude=["parser", "tagger", "ner", "lemmatizer"])
    
    output_hmdd = str(OUTPUTS_DIR / 'HMDD' /'distances.txt')
    output_bg = str(OUTPUTS_DIR / 'disease_and_mir' / 'distances.txt')
    
    mir_resources = MirResourceLoader.load(
        mirna_taxons_path=MirbaseResources.mirna_taxons_path,
        mirna_2_prefix_path=MirbaseResources.mirna_to_prefix_path,
        family_normalizer_path=MirbaseResources.family_norm_path,
        precursor_normalizer_path=MirbaseResources.precursor_norm_path,
        mature_normalizer_path=MirbaseResources.mature_norm_path,
        precursor_ambiguous_path=MirbaseResources.precursor_ambi_path,
        mature_ambiguous_path=MirbaseResources.mature_ambi_path
    )
    
    normalizers = {
        HitType.MIR: MirNormalizer(SentenceReader(resources.CORPUS_SAMPLE), mir_resources),
        HitType.DISEASE: DefaultNormalizer()
    }
    
    scorer = HitScorer(type_to_onto)
    
    article_stream_hmdd = processor_hmdd.read_articles(sort=True)
    article_stream_bg = Processor(hits_processor=processor_bg, normalizers=normalizers, scorer=scorer).get_normalized_article_stream()
    
    sample_distances(article_stream_bg, sentence_reader_bg, nlp, output_bg, use_normalized=True)
    sample_distances(article_stream_hmdd, sentence_reader_hmdd, nlp, output_hmdd, use_normalized=False)

