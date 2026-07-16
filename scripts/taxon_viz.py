"""
Plots the distribution of unique taxon mentions per article,
split into PMC articles vs PubMed abstracts.

Run this in the same environment as your HitsProcessor.
"""

from collections import defaultdict
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from python.src.NER.hitsUtils import HitsProcessor
import numpy as np

# ---- 1. Aggregate unique resolved taxon ids per article ----

# article_id -> set of unique synonym_ids (resolved hits only)
article_taxa = defaultdict(set)
# article_id -> 'pmc' or 'pubmed', determined once per article from sentence_id prefix
article_source = {}

n_hits = 0
n_unresolved_skipped = 0

hits_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/linnaeus_hits/linnaeus_hits.hits'
synfile_map = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/linnaeus_hits/synfile.map'
basepath = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/taxonomy_no_dups/'
file_names = ['linnaeus_cell_lines.syn', 'linnaeus_proxy.syn', 'linnaeus_species.syn']
synfile_paths = (basepath + file_name for file_name in file_names)
processor = HitsProcessor(hits_path=hits_path, synonym_paths=synfile_paths, synfile_map=synfile_map, low_memory=False)

for hit in processor.get_hits(append_article_id=True, sort=True, resolve_ambiguous=True):
    n_hits += 1
    article_id = hit['article_id']

    if article_id not in article_source:
        article_source[article_id] = 'pmc' if article_id.startswith('PMC') else 'pubmed'

    if not hit['resolved']:
        n_unresolved_skipped += 1
        continue

    article_taxa[article_id].add(hit['synonym_id'])

print(f"Total hits processed: {n_hits}")
print(f"Unresolved hits skipped: {n_unresolved_skipped} ({n_unresolved_skipped / n_hits:.1%})")
print(f"Articles seen: {len(article_taxa)}")

pmc_counts = np.array([
    len(taxa) for aid, taxa in article_taxa.items() if article_source[aid] == 'pmc'
])
pubmed_counts = np.array([
    len(taxa) for aid, taxa in article_taxa.items() if article_source[aid] == 'pubmed'
])

print(f"PMC articles: {len(pmc_counts)}, max={pmc_counts.max()}, p99={np.percentile(pmc_counts, 99):.0f}")
print(f"PubMed articles: {len(pubmed_counts)}, max={pubmed_counts.max()}, p99={np.percentile(pubmed_counts, 99):.0f}")

# Report the most extreme outliers explicitly, since they get clipped from the plot view
pmc_outlier_threshold = np.percentile(pmc_counts, 99.5)
n_pmc_outliers = int((pmc_counts > pmc_outlier_threshold).sum())
print(f"PMC articles above p99.5 ({pmc_outlier_threshold:.0f}): {n_pmc_outliers}")

# ---- 2. Plot ----

plt.rcParams.update({
    'font.family': 'DejaVu Sans',
    'font.size': 11,
    'axes.edgecolor': '#444444',
    'axes.linewidth': 0.8,
})

INK = '#2b2b2b'
PMC_COLOR = '#3b6e8f'
PUBMED_COLOR = '#b5673a'
GRID_COLOR = '#dddddd'

fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=False)

for ax, counts, label, color in [
    (axes[0], pmc_counts, 'PMC full-text articles', PMC_COLOR),
    (axes[1], pubmed_counts, 'PubMed abstracts', PUBMED_COLOR),
]:
    if len(counts) == 0:
        ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes, color=INK)
        continue

    median = int(np.median(counts))
    # Clip the visible x-range to the 99th percentile so a handful of extreme
    # outlier articles don't compress the entire informative range into a
    # single pixel-wide bar near zero. Outliers are still counted in the
    # histogram totals printed above, just not individually visible here.
    x_max = max(int(np.percentile(counts, 99)) + 1, median + 2)
    bins = range(0, x_max + 2)

    ax.hist(counts, bins=bins, color=color, edgecolor='white', linewidth=0.6, align='left')
    ax.set_xlim(-0.5, x_max + 0.5)
    ax.set_title(f"{label}\n(n={len(counts):,} articles)", color=INK, fontsize=12, loc='left')
    ax.set_xlabel('Unique taxon mentions per article', color=INK)
    ax.set_ylabel('Number of articles', color=INK)
    ax.set_yscale('log')
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(
        lambda x, _: f'{int(x):,}' if x >= 1 else ''
    ))
    ax.grid(axis='y', which='major', color=GRID_COLOR, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ['top', 'right']:
        ax.spines[spine].set_visible(False)

    ax.axvline(median, color=INK, linestyle='--', linewidth=1, alpha=0.6)
    ax.text(
        median + x_max * 0.02, ax.get_ylim()[1] * 0.7, f'median={median}',
        color=INK, fontsize=9, va='top',
    )

    n_clipped = int((counts > x_max).sum())
    if n_clipped > 0:
        ax.text(
            0.98, 0.95, f'{n_clipped:,} articles >{x_max} not shown',
            ha='right', va='top', transform=ax.transAxes,
            color=INK, fontsize=8.5, style='italic', alpha=0.75,
        )

fig.suptitle('Unique taxon mentions per article', fontsize=15, color=INK, y=1.02)
fig.tight_layout()
fig.savefig('taxon_hits_per_article.png', dpi=150, bbox_inches='tight')
