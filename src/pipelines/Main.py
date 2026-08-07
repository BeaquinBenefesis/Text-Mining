from sentence_utils import SentenceReader
from hitsUtils import HitsProcessor
from resources import MirResourceLoader
from NormUtils import MirNormalizer, DefaultNormalizer
from models import HitType
from Processor import Processor
from tqdm import tqdm
from src.textmining.analysis import Grouper
import time

hits = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/everything/sample.hits'
synfile_map = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/everything/synfile.map'
synfile_type_map = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/everything/synfile_type.map'
mirna_taxons_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/mirna_taxons.tsv'
sents = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/corpus/original/everything_sorted.sent'
mirna_2_prefix_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/mirna_prefix_mapping.json'
family_normalizer_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/family_normalization_dict.json'
precursor_normalizer_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/precursor_normalization_dict.json'
mature_normalizer_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/mature_normalization_dict.json'
precursor_ambiguous_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/precursor_id_conflicts.tsv'
mature_ambiguous_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/mirbase/normalization/mature_id_conflicts.tsv'

print('Start')
sentence_reader = SentenceReader(sentence_path=sents)
hits_processor = HitsProcessor(hits, synfile_map, synfile_type_map)
mir_resources = MirResourceLoader.load(mirna_taxons_path=mirna_taxons_path,
                                       mirna_2_prefix_path=mirna_2_prefix_path,
                                       family_normalizer_path=family_normalizer_path,
                                       precursor_normalizer_path=precursor_normalizer_path,
                                       mature_normalizer_path=mature_normalizer_path,
                                       precursor_ambiguous_path=precursor_ambiguous_path,
                                       mature_ambiguous_path=mature_ambiguous_path)
mir_normalizer = MirNormalizer(sentence_reader=sentence_reader,
                               resources=mir_resources)
default_normalizer = DefaultNormalizer()
normalizers = {HitType.MIR: mir_normalizer, 
               HitType.TAXON: default_normalizer, 
               HitType.DISEASE: default_normalizer,
               HitType.TISSUE: default_normalizer, 
               HitType.CELL: default_normalizer,
               HitType.PATHWAY: default_normalizer}
main_processor = Processor(hits_processor, normalizers)

grouper = Grouper()


print('Init done')
pipeline = grouper.extract_cooccurrences(main_processor.get_normalized_hit_stream(sort_hits=False, print_summary=True, resolve_ambiguous_hits=True))

counter = 0
for association in pipeline:
    counter += 1
