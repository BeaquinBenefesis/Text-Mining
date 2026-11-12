"""PubMed articles per year whose title or abstract mentions a miRNA (introduction figure).

Counts come from NCBI E-utilities and are cached, so re-plotting needs no network.

    PYTHONPATH=src .venv/bin/python scripts/evaluation/pubmed_mirna_growth.py
"""
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

QUERY = "(microRNA[tiab] OR microRNAs[tiab] OR miRNA[tiab] OR miRNAs[tiab])"
YEARS = range(2000, 2026)
CACHE = Path("outputs/pubmed_mirna_counts.json")
FIGURE = "/mnt/raidbio2/extstud/studtemp/mitsopoulos/bachelor-thesis/figures/pubmed_mirna_growth"


def fetch() -> dict:
    counts = {}
    for year in YEARS:
        url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urllib.parse.urlencode(
            {"db": "pubmed", "term": f"{QUERY} AND {year}[dp]", "retmode": "json", "tool": "thesis_plot"})
        counts[year] = int(json.load(urllib.request.urlopen(url))["esearchresult"]["count"])
        time.sleep(0.4)                                   # stay below 3 requests/s without an API key
    return counts


def main() -> None:
    if CACHE.exists():
        counts = {int(y): n for y, n in json.loads(CACHE.read_text()).items()}
    else:
        counts = fetch()
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(json.dumps(counts))
    print(f"total {sum(counts.values()):,}, peak {max(counts, key=counts.get)}: {max(counts.values()):,}")

    plt.rcParams.update({"font.size": 9, "pdf.fonttype": 42, "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(4.8, 2.4), layout="constrained")
    ax.bar(list(counts), list(counts.values()), width=0.8, color="#0072B2")
    ax.set_xlabel("Publication year")
    ax.set_ylabel("Articles")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.grid(axis="y", color="0.9", lw=0.6)
    ax.set_axisbelow(True)
    ax.set_xlim(min(YEARS) - 0.7, max(YEARS) + 0.7)
    fig.savefig(f"{FIGURE}.pdf")
    fig.savefig(f"{FIGURE}.png", dpi=200)


if __name__ == "__main__":
    main()
