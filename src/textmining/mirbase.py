import csv
from pathlib import Path

def _read_tsv_rows(path):
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)

def load_mirbase(
    families_tsv: str,
    precursors_tsv: str,
    mature_tsv: str,
    parent_to_child_tsv: str,
    relationship: str = "is_a",
):
    nodes = {}
    edges = []

    for row in _read_tsv_rows(families_tsv):
        label = row["id"].strip()
        accession = row["accession"].strip()

        nodes[accession] = {
            "name": label,
            "type": "family",
            "accession": accession,
        }

    for row in _read_tsv_rows(precursors_tsv):
        label = row["id"].strip()
        accession = row["accession"].strip()

        nodes[accession] = {
            "name": label,
            "type": "precursor",
            "accession": accession,
        }

    for row in _read_tsv_rows(mature_tsv):
        label = row["id"].strip()
        accession = row["accession"].strip()

        nodes[accession] = {
            "name": label,
            "type": "mature",
            "accession": accession,
        }


    for row in _read_tsv_rows(parent_to_child_tsv):
        parent = row["parent"].strip()  # MIPF...
        child = row["child"].strip()    # MI...

        if parent not in nodes:
            raise ValueError(f"Unknown family accession in parent_to_child.tsv: {parent}")
        if child not in nodes:
            raise ValueError(f"Unknown precursor accession in parent_to_child.tsv: {child}")

        edges.append((child, parent, relationship))

    return edges, nodes, relationship
