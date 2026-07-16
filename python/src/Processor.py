from hitsUtils import HitsProcessor
from hitsUtils import HitType
from collections import deque
from sentence_utils import SentenceReader
from collections import Counter
from tqdm import tqdm
from NormUtils import MirNormalizer
from NormUtils import EntityNormalizer
from ArticleUtils import ArticleContext
from NormUtils import MirIdMapper
from NormUtils import TaxonNormalizer

class Processor:
    
    def __init__(self,
                 hits_processor: HitsProcessor,
                 normalizers: dict[HitType, EntityNormalizer],
                 low_memory=False):
        
        # BASIC PROCESSING
        self.hits_iter = hits_processor.get_hits(append_article_id=True, append_synfile_type=True, sort=False, resolve_ambiguous=True)
        self.sentence_reader = sentence_reader
        
        # NORMALIZERS
        self.normalizers = normalizers    
        
    # HERE THE PROCESSING WILL HAPPEN
    def get_normalized_hit_stream(self):
        article_context = ArticleContext()
        article_hits = deque()
        prev_article = None
        for hit in self.hits_iter:
            if prev_article and prev_article != hit['article_id']:
                yield from self._normalize_article(article_hits, article_context)
                article_context.clear()
                article_hits.clear()
            prev_article = hit['article_id']
            article_context.add_hit(hit)
            article_hits.append(hit)
        
        yield from self._normalize_article(article_hits, article_context)

    def _normalize_article(self, hits, context):
        for hit in hits:
            yield from self.normalizers[hit['type']].normalize(hit, context)

    # Returns a dictionary of taxons and their article relevance
    # tax_buffer is a deque containing all taxons in article
    #TODO: implement the relevance scoring
    def _compute_taxon_relevance(self, tax_buffer: deque) -> dict:
        return {tax['synonym_id'] : 1 for tax in tax_buffer}


hits = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/mir_and_taxon_hits/sorted.hits'
synfile_map = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/mir_and_taxon_hits/synfile.map'
synfile_type_map = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/synfile_type.map'
mirna_taxons_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/mirna_taxons.tsv'
sents = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/corpus/original/everything_sorted.sent'
mirna_2_prefix_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/mirna_prefix_mapping.json'
family_normalizer_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/family_normalization_dict.json'
precursor_normalizer_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/precursor_normalization_dict.json'
mature_normalizer_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/mature_normalization_dict.json'
precursor_ambiguous_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/precursor_id_conflicts.tsv'
mature_ambiguous_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/mature_id_conflicts.tsv'

sentence_reader = SentenceReader(sentence_path=sents)
hits_processor = HitsProcessor(hits, synfile_map, synfile_type_map)
mir_normalizer = MirNormalizer(sentence_reader=sentence_reader,
                               mirna_taxons_path=mirna_taxons_path,
                               mirna_2_prefix_path=mirna_2_prefix_path,
                               family_normalizer_path=family_normalizer_path,
                               precursor_normalizer_path=precursor_normalizer_path,
                               mature_normalizer_path=mature_normalizer_path,
                               precursor_ambiguous_path=precursor_ambiguous_path,
                               mature_ambiguous_path=mature_ambiguous_path)
taxon_normalizer = TaxonNormalizer()
normalizers = {HitType.MIR: mir_normalizer, HitType.TAXON: taxon_normalizer}
main_processor = Processor(hits_processor, normalizers)


status = Counter()
ambiguous_ids = Counter()
not_in_mirbase = Counter()

# Open the file in write mode
with open('normalized.hits', 'w') as out:
    # Wrap the generator stream with tqdm
    # 'desc' adds a custom text label in front of the progress indicator
    for hit in tqdm(main_processor.get_normalized_hit_stream(), desc="Normalizing miRNAs"):
        if not hit['type'] == HitType.MIR:
            continue
        hit_status = hit['status']
        vals = '\t'.join(str(val) for val in hit.values())
        out.write(f'{vals}\n')
        status[hit_status] += 1
        if hit['status'] == 'AMBIGUOUS_TYPE':
            ambiguous_ids[MirIdMapper.resolve_token(hit['synonym_id']) + hit.get('suffix', '')] += 1
        elif hit['status'] == 'NOT_IN_MIRBASE':
            not_in_mirbase[hit.get('prefix', '') + hit['synonym_id'] + hit.get('suffix', '')] += 1

print(ambiguous_ids.most_common(100))
with open('not_in_mirbase.txt', 'w') as f:
    for value, count in not_in_mirbase.items():
        f.write(f'{value}\t{count}\n')
print(status)