#!/usr/bin/env python3
"""
parse_mirbase.py

Parse a miRBase-style flat file (e.g. miRNA.dat) and, optionally, its
companion "dead" file (e.g. miRNA.dead) listing retired/withdrawn entries,
and extract:

  1) precursors.tsv   -> precursor id, accession ("MI..."), and a "dead" flag
  2) mature.tsv        -> mature miRNA id, accession ("MIMAT..."), and a "dead" flag
  3) mi_to_mimat.tsv   -> mapping of precursor accession (MI...) to mature accession
                          (MIMAT...), one row per MIMAT accession listed under that
                          precursor's FT table (live entries only; dead entries have
                          no FT table to derive a mapping from).

The dead file uses a different, simpler record format (still "//"-terminated
blocks), e.g.:

    AC   MI0000092
    ID   hsa-mir-91
    PI   hsa-mir-91-13
    FW   MI0000071
    CC   miR-91 is expressed from the 5' arm of the mir-17 precursor hairpin.
    //

Each dead entry's accession prefix determines whether it belongs in the
precursor file ("MI...", but not "MIMAT...") or the mature file ("MIMAT...").

Usage:
    python3 parse_mirbase.py input.dat -o outdir [--dead input.dead]
"""

import argparse
import os
import re
import sys


def parse_entries(text):
    """Split the file into individual entries on lines that are exactly '//'."""
    entries = []
    current = []
    for line in text.splitlines():
        if line.strip() == "//":
            if current:
                entries.append(current)
            current = []
        else:
            current.append(line)
    if current:
        entries.append(current)
    return entries


def parse_entry(lines):
    """
    Parse a single entry (list of lines, no trailing '//') and return a dict:
        {
          "id": <precursor id>,
          "ac": <precursor accession, MI...>,
          "matures": [ {"product": ..., "accession": ...}, ... ]
        }
    """
    precursor_id = None
    precursor_ac = None
    matures = []
    current_mature = None

    for line in lines:
        # ID line, e.g.: "ID   cel-let-7         standard; RNA; CEL; 99 BP."
        if line.startswith("ID"):
            rest = line[2:].strip()
            # id is the first whitespace-delimited token
            precursor_id = rest.split()[0] if rest else None

        # AC line, e.g.: "AC   MI0000001;"
        elif line.startswith("AC") and precursor_ac is None:
            rest = line[2:].strip()
            precursor_ac = rest.split(";")[0].strip()

        # FT feature line, e.g.: "FT   miRNA           17..38"
        elif line.startswith("FT"):
            ft_body = line[2:].strip()
            # A new "miRNA" feature line starts a new mature entry
            if re.match(r"^miRNA\s+\d", ft_body):
                if current_mature is not None:
                    matures.append(current_mature)
                current_mature = {"product": None, "accession": None}
            else:
                # Qualifier lines, e.g. /accession="MIMAT0000001" or /product="cel-let-7-5p"
                acc_match = re.search(r'/accession="([^"]+)"', ft_body)
                prod_match = re.search(r'/product="([^"]+)"', ft_body)
                if current_mature is not None:
                    if acc_match:
                        current_mature["accession"] = acc_match.group(1)
                    if prod_match:
                        current_mature["product"] = prod_match.group(1)

    if current_mature is not None:
        matures.append(current_mature)

    return {
        "id": precursor_id,
        "ac": precursor_ac,
        "matures": [m for m in matures if m["accession"] or m["product"]],
    }


def parse_dead_entry(lines):
    """
    Parse a single entry (list of lines, no trailing '//') from a miRNA.dead
    file and return a dict: {"id": ..., "ac": ...}.

    Dead-file records look like:
        AC   MI0000092
        ID   hsa-mir-91
        PI   hsa-mir-91-13
        FW   MI0000071
        CC   ...
    """
    dead_id = None
    dead_ac = None

    for line in lines:
        if line.startswith("AC") and dead_ac is None:
            dead_ac = line[2:].strip().rstrip(";").strip()
        elif line.startswith("ID") and dead_id is None:
            dead_id = line[2:].strip().split()[0] if line[2:].strip() else None

    return {"id": dead_id, "ac": dead_ac}


def parse_dead_file(text):
    """
    Parse a whole miRNA.dead file into a list of {"id", "ac"} dicts,
    reusing the same '//'-block splitting logic as the main .dat file.
    """
    entries_raw = parse_entries(text)
    entries = [parse_dead_entry(e) for e in entries_raw]
    return [e for e in entries if e["ac"]]


def classify_dead_accession(accession):
    """
    Determine whether a dead-file accession belongs to a precursor (MI...)
    or a mature miRNA (MIMAT...), based on its prefix.

    Returns "precursor", "mature", or None if unrecognized.
    """
    if accession.startswith("MIMAT"):
        return "mature"
    if accession.startswith("MI"):
        return "precursor"
    return None


def main():
    parser = argparse.ArgumentParser(description="Extract precursor/mature miRNA data and MI->MIMAT mapping from a miRBase .dat file, optionally merging in dead/retired entries from a miRNA.dead file.")
    parser.add_argument("input", help="Path to the miRBase .dat file")
    parser.add_argument("-o", "--outdir", default=".", help="Output directory (default: current directory)")
    parser.add_argument("--dead", help="Path to the miRBase .dead file (optional)", default=None)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        text = f.read()

    os.makedirs(args.outdir, exist_ok=True)

    entries_raw = parse_entries(text)
    entries = [parse_entry(e) for e in entries_raw]

    precursor_path = os.path.join(args.outdir, "precursors.tsv")
    mature_path = os.path.join(args.outdir, "mature.tsv")
    mapping_path = os.path.join(args.outdir, "mi_to_mimat.tsv")

    n_precursors = 0
    n_matures = 0
    n_mappings = 0

    with open(precursor_path, "w", encoding="utf-8") as pf, \
         open(mature_path, "w", encoding="utf-8") as mf, \
         open(mapping_path, "w", encoding="utf-8") as xf:

        pf.write("id\taccession\tdead\n")
        mf.write("id\taccession\tdead\n")
        xf.write("MI\tMIMAT\n")

        for entry in entries:
            if entry["id"] is None or entry["ac"] is None:
                # Skip malformed entries silently, but keep going
                continue

            pf.write(f"{entry['id']}\t{entry['ac']}\t0\n")
            n_precursors += 1

            for mature in entry["matures"]:
                mid = mature["product"] or ""
                mac = mature["accession"] or ""
                if mid or mac:
                    mf.write(f"{mid}\t{mac}\t0\n")
                    n_matures += 1
                if mac:
                    xf.write(f"{entry['ac']}\t{mac}\n")
                    n_mappings += 1

        n_dead_precursors = 0
        n_dead_matures = 0
        n_dead_unrecognized = 0

        if args.dead:
            with open(args.dead, "r", encoding="utf-8") as f:
                dead_text = f.read()
            dead_entries = parse_dead_file(dead_text)

            for dead in dead_entries:
                kind = classify_dead_accession(dead["ac"])
                did = dead["id"] or ""
                dac = dead["ac"]

                if kind == "precursor":
                    pf.write(f"{did}\t{dac}\t1\n")
                    n_dead_precursors += 1
                elif kind == "mature":
                    mf.write(f"{did}\t{dac}\t1\n")
                    n_dead_matures += 1
                else:
                    n_dead_unrecognized += 1
                    print(f"Warning: could not classify dead accession '{dac}' (id='{did}') as precursor or mature; skipped.", file=sys.stderr)

    print(f"Parsed {len(entries)} live entries.")
    print(f"  precursors.tsv   -> {n_precursors} live + {n_dead_precursors} dead rows  ({precursor_path})")
    print(f"  mature.tsv       -> {n_matures} live + {n_dead_matures} dead rows  ({mature_path})")
    print(f"  mi_to_mimat.tsv  -> {n_mappings} rows  ({mapping_path})")
    if args.dead and n_dead_unrecognized:
        print(f"  ({n_dead_unrecognized} dead entries had an unrecognized accession prefix and were skipped)")


if __name__ == "__main__":
    main()