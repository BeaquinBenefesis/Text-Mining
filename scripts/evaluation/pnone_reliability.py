"""Reliability of P(none) of the saved relation model against the Opus labels of the test set.

Each pair goes through RelationAnnotator, the code path of the corpus run. Everything here is
agreement with Opus (an LLM), not with verified truth.

    PYTHONPATH=src .venv/bin/python scripts/evaluation/pnone_reliability.py
"""
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from sklearn.metrics import f1_score

from textmining.bert import RelationAnnotator, untag
from textmining.enums import HitType, Label

ANNOTATED = "/mnt/raidbio2/extstud/studtemp/mitsopoulos/mirna-annotation/runs/opus_balanced_v06/annotated.tsv"
MODEL_DIR = Path("data/models/relation_pubmedbert")
TABLE = "outputs/pnone_reliability.tsv"
FIGURE = "/mnt/raidbio2/extstud/studtemp/mitsopoulos/bachelor-thesis/figures/pnone_reliability"
EXPECTED_ACCURACY, EXPECTED_MACRO_F1 = 0.791, 0.789       # stored with the saved model
Z = 1.959964                                              # 95% interval
N_BINS = 10


def load_test() -> pd.DataFrame:
    """The Opus test set, read as in analysis/training.ipynb."""
    test = pd.read_csv(ANNOTATED, sep="\t", quoting=csv.QUOTE_NONE, dtype={"sentence_id": str})
    test["sentence"] = test["sentence"].str.replace(r'^"(.*)"$', r"\1", regex=True)
    test["clean"] = ~test["error"].fillna("").str.contains("unclear|ner_error")
    return test


def as_cooccurrence(sentence: str) -> tuple:
    """(text, mirna_span, term_span, term_type) of a tagged sentence, as RelationAnnotator.annotate takes them."""
    text, spans = untag(sentence)
    mirna = [s for s in spans if s[2] == HitType.MIR.value]
    term = [s for s in spans if s[2] != HitType.MIR.value]
    assert len(mirna) == len(term) == 1, sentence
    return text, mirna[0][:2], term[0][:2], HitType(term[0][2])


def wilson(k: int, n: int) -> tuple[float, float]:
    share, z2 = k / n, Z ** 2
    centre = (share + z2 / (2 * n)) / (1 + z2 / n)
    half = Z * np.sqrt(share * (1 - share) / n + z2 / (4 * n ** 2)) / (1 + z2 / n)
    return max(centre - half, 0.0), min(centre + half, 1.0)


def equal_width(p: np.ndarray) -> list[np.ndarray]:
    index = np.minimum((p * N_BINS).astype(int), N_BINS - 1)
    return [np.flatnonzero(index == b) for b in range(N_BINS)]


def equal_frequency(p: np.ndarray) -> list[np.ndarray]:
    return np.array_split(np.argsort(p), N_BINS)


def ece(p: np.ndarray, y: np.ndarray, bins: list[np.ndarray]) -> float:
    return sum(abs(p[b].mean() - y[b].mean()) * len(b) for b in bins if len(b)) / len(p)


def ece_if_calibrated(p: np.ndarray, bins: list[np.ndarray], runs: int = 2000) -> float:
    """Mean ECE if the outcomes really were drawn from p: ECE is above 0 by chance alone."""
    rng = np.random.default_rng(0)
    return float(np.mean([ece(p, rng.random(len(p)) < p, bins) for _ in range(runs)]))


def row(subset: str, binning: str, name, p: np.ndarray, y: np.ndarray) -> dict:
    """One bin, or the whole subset: counts, means and the Wilson interval."""
    r = {"subset": subset, "binning": binning, "bin": name, "n": len(p)}
    if len(p):
        low, high = wilson(int(y.sum()), len(p))
        r |= {"min_p_none": p.min(), "max_p_none": p.max(), "n_none": int(y.sum()), "mean_p_none": p.mean(),
              "share_none": y.mean(), "wilson_low": low, "wilson_high": high}
    return r


def table(subset: str, p: np.ndarray, y: np.ndarray) -> list[dict]:
    rows = []
    for binning, make_bins in (("equal_width", equal_width), ("equal_frequency", equal_frequency)):
        bins = make_bins(p)
        rows += [row(subset, binning, i + 1, p[b], y[b]) for i, b in enumerate(bins)]
        rows.append(row(subset, binning, "all", p, y) | {
            "ece": ece(p, y, bins), "ece_if_calibrated": ece_if_calibrated(p, bins),
            "brier": np.mean((p - y) ** 2), "brier_base_rate": y.mean() * (1 - y.mean()),
            "sum_p_none": p.sum(), "mean_w": 1 - p.mean(), "share_not_none": 1 - y.mean()})
    return rows


def plot(rows: pd.DataFrame) -> None:
    """Equal-width reliability curve above the bin sizes."""
    bins = rows[(rows.subset == "all") & (rows.binning == "equal_width") & (rows.bin != "all")]
    used = bins[bins.n > 0]
    plt.rcParams.update({"font.size": 9, "pdf.fonttype": 42, "axes.spines.top": False, "axes.spines.right": False})
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(4.8, 3.0), sharex=True, height_ratios=[3, 1],
                                      layout="constrained")
    top.plot([0, 1], [0, 1], "--", color="0.5", lw=1, label="perfect calibration")
    top.errorbar(used.mean_p_none, used.share_none, fmt="o-", ms=4.5, lw=1.2, capsize=2.5, color="#0072B2",
                 yerr=[used.share_none - used.wilson_low, used.wilson_high - used.share_none],
                 label="model (95% Wilson interval)")
    top.set(ylabel="Share labeled none by Opus", xlim=(0, 1), ylim=(0, 1), xticks=np.arange(0, 1.01, 0.2))
    top.legend(frameon=False, loc="upper left", fontsize=8)

    centres = np.arange(N_BINS) / N_BINS + 0.05
    bottom.bar(centres, bins.n, width=0.09, color="0.6")
    bottom.set(xlabel="Predicted P(none)", ylabel="Pairs", ylim=(0, bins.n.max() * 1.3))
    for x, n in zip(centres, bins.n):
        bottom.annotate(str(n), (x, n), xytext=(0, 1.5), textcoords="offset points",
                        ha="center", va="bottom", fontsize=7)
    fig.savefig(f"{FIGURE}.pdf")
    fig.savefig(f"{FIGURE}.png", dpi=200)


def main() -> None:
    torch.set_num_threads(8)
    test = load_test()
    annotator = RelationAnnotator(MODEL_DIR, device="cpu")
    probabilities = list(annotator.annotate(as_cooccurrence(s) for s in test["sentence"]))
    assert all(probabilities), "a test pair could not be labelled"
    assert all(len(pair) == 9 for pair in probabilities)

    predicted = [max(pair, key=pair.get).value for pair in probabilities]
    accuracy = np.mean(test["label"] == predicted)
    macro_f1 = f1_score(test["label"], predicted, average="macro")
    print(f"agreement with Opus {accuracy:.4f} (stored {EXPECTED_ACCURACY}), "
          f"macro-F1 {macro_f1:.4f} (stored {EXPECTED_MACRO_F1})")
    if abs(accuracy - EXPECTED_ACCURACY) > 0.005 or abs(macro_f1 - EXPECTED_MACRO_F1) > 0.005:
        raise SystemExit("sanity check failed: not the probabilities of the saved model")

    p = np.array([pair[Label.NONE] for pair in probabilities])
    y = (test["label"] == "none").to_numpy().astype(float)
    clean = test["clean"].to_numpy()
    assert clean.sum() == 771
    rows = pd.DataFrame(table("all", p, y) + table("no_unclear_or_ner_error", p[clean], y[clean]))
    rows.to_csv(TABLE, sep="\t", index=False, float_format="%.4f")
    print(rows.drop(columns="subset").to_string())
    plot(rows)


if __name__ == "__main__":
    main()
