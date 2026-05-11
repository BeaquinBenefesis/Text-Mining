import spacy

nlp = spacy.load("en_ner_bionlp13cg_md")
text = """
MicroRNA dysregulation has emerged as a critical mechanism in the pathogenesis of 
metabolic and oncological disorders. In hepatocellular carcinoma tissue isolated from 
Homo sapiens patients, hsa-miR-21-5p was found to be significantly upregulated 
(4.1-fold, p<0.001), while hsa-miR-122-5p — normally the most abundant miRNA in 
hepatocytes — showed marked downregulation. Overexpression of hsa-miR-21-5p was 
shown to suppress PTEN, a key negative regulator of the PI3K/AKT/mTOR signalling 
pathway, thereby promoting uncontrolled proliferation of HepG2 cells. Parallel 
findings were reported in peripheral blood mononuclear cells derived from Mus musculus 
models of non-alcoholic fatty liver disease, where hsa-miR-155-5p activated the 
NF-κB signalling pathway and drove pro-inflammatory cytokine release in Kupffer cells.

Subsequent analysis of colorectal adenocarcinoma specimens from Homo sapiens revealed 
co-dysregulation of hsa-miR-34a-5p and hsa-miR-200c-3p in colonic epithelium, with 
downstream suppression of the Wnt/β-catenin pathway and partial restoration of 
E-cadherin expression in HCT116 cell lines. Notably, serum levels of hsa-miR-21-5p 
were also elevated in type 2 diabetes mellitus patients, where it was linked to 
impaired insulin signalling through inhibition of the MAPK/ERK pathway in pancreatic 
beta cells. These findings collectively suggest that a small set of miRNAs exerts 
pleiotropic effects across multiple disease contexts by converging on shared regulatory 
pathways, underscoring their potential as both diagnostic biomarkers and therapeutic 
targets in Rattus norvegicus and Homo sapiens model systems alike."""

doc = nlp(text)

for token in doc:
    print(token.text, token.pos_, token.dep_)
