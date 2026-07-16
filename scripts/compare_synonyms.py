from python.src.SynFileUtils import compare_synfiles

go = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/go'
pw = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/pw'
upa = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/upa'

compare_synfiles(pw, upa, False)