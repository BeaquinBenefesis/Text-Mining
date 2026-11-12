import json
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

from textmining.config import MirbaseResources
from textmining.enums import HitType
from textmining.hit_utils import LcaResolver
from textmining.models import CoOccurence


class OrganismConsistencyFilter:
    """Drops miRNA-gene co-occurrences whose miRNA and gene belong to different organisms."""

    def __init__(self, mir_organisms: dict[str, str], gene_organisms: dict[str, str], viral_taxa: set[str]):
        self.mir_organisms = mir_organisms      # miRNA accession -> taxon id; families have none
        self.gene_organisms = gene_organisms    # composite gene id -> taxon id
        self.viral_taxa = viral_taxa
        self.dropped = 0

    def is_consistent(self, cooc: CoOccurence) -> bool:
        if cooc.entity_types[1] != HitType.GENE:
            return True
        mir_acc, gene_id = cooc.normalized_ids
        mir_taxon = self.mir_organisms.get(mir_acc)
        # families have no organism; viral miRNAs act on the genes of their host
        if mir_taxon is None or mir_taxon in self.viral_taxa:
            return True
        return mir_taxon == self.gene_organisms[gene_id]

    def filter(self, cooccurrences: Iterable[CoOccurence]) -> Iterator[CoOccurence]:
        for cooc in cooccurrences:
            if self.is_consistent(cooc):
                yield cooc
            else:
                self.dropped += 1

    @classmethod
    def load(cls, mirbase: MirbaseResources, gene_taxon_map: Path, taxon_resolver: LcaResolver):
        taxa = pd.read_csv(mirbase.mirna_taxons_path, sep="\t")
        prefix_taxon = dict(zip(taxa["prefix"], taxa["id"]))
        mirnas = pd.concat([pd.read_csv(p, sep="\t") for p in (mirbase.mature_path, mirbase.precursor_path)])
        # the organism of a precursor or mature accession is the prefix of its name
        mir_organisms = dict(zip(mirnas["accession"], mirnas["id"].str.split("-", n=1).str[0].map(prefix_taxon)))
        with open(gene_taxon_map) as f:
            gene_organisms = json.load(f)
        # canonical_id follows taxa that later NCBI Taxonomy releases merged into others
        viral_taxa = {t for t in taxa["id"]
                      if (current := taxon_resolver.canonical_id(t)) and "NCBITaxon_10239" in taxon_resolver.lineage(current)}
        return cls(mir_organisms, gene_organisms, viral_taxa)
