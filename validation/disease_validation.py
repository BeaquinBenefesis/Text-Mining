from collections import Counter
from dataclasses import dataclass
from src.textmining.syngrep import run_syngrep
from src.textmining.models import HitType, NormalizedHit, CandidateHit
from src.textmining.hit_utils import HitsProcessor
from src.textmining.article_utils import ArticleSource, ArticleRecord
from collections import defaultdict
import json
from typing import Iterator
from src.textmining.ontology import OntologyGraph, disease_equivalence_fn
import csv
from pathlib import Path


def _end(start, length):
    return start + length

def _intersection(a_start, a_len, b_start, b_len):
    a_end = _end(a_start, a_len)
    b_end = _end(b_start, b_len)
    return max(0, min(a_end, b_end) - max(a_start, b_start))

def exact_match(p, g):
    if p.start_position == g.start_position and p.hit_length == g.hit_length:
        return p.hit_length
    return 0

def overlap_match(p, g):
    return _intersection(p.start_position, p.hit_length, g.start_position, g.hit_length)

@dataclass
class Stat:
    name: str
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def inc_tp(self):
        self.tp += 1
        
    def inc_fp(self):
        self.fp += 1
        
    def inc_fn(self):
        self.fn += 1
    
    @property
    def true_positives(self) -> int:
        return self.tp
    
    @property
    def false_positives(self) -> int:
        return self.fp
    
    @property
    def false_negatives(self) -> int:
        return self.fn
    
    @property
    def total_ground_truth(self) -> int:
        return self.tp + self.fn
    
    @property
    def total_predicted(self) -> int:
        return self.tp + self.fp
    
    def calc_precision(self) -> float:
        total = self.total_predicted
        return self.tp / total if total > 0 else 0.0
    
    def calc_recall(self) -> float:
        total = self.total_ground_truth
        return self.tp / total if total > 0 else 0.0
            
    def calc_f1(self) -> float:
        p, r = self.calc_precision(), self.calc_recall()
        return (2 * p * r) / (p + r) if (p + r) > 0 else 0.0
    
    def print_summary(self):
        p, r, f1 = self.calc_precision(), self.calc_recall(), self.calc_f1()
        
        print("\n" + "=" * 50)
        print(f"{self.name}: {f'EVALUATION SUMMARY':^50}")
        print("=" * 50)
        print(f"  True Positives  (TP) : {self.true_positives:>10,d}")
        print(f"  False Positives (FP) : {self.false_positives:>10,d}")
        print(f"  False Negatives (FN) : {self.false_negatives:>10,d}")
        print("-" * 50)
        print(f"  Total Ground Truth   : {self.total_ground_truth:>10,d}")
        print(f"  Total Predicted      : {self.total_predicted:>10,d}")
        print("-" * 50)
        print(f"  Precision            : {p:>10.4f} ({p:.2%})")
        print(f"  Recall               : {r:>10.4f} ({r:.2%})")
        print(f"  F1-Score             : {f1:>10.4f}")
        print("=" * 50 + "\n")

class Test:
    def __init__(
        self,
        gold_hits_path: str,
        pred_path: str,
        synfile_map_path: str,
        synfile_type_map_path: str,
        id_map_path: str,
        type_to_ontology: dict[HitType, OntologyGraph]
    ):
        self.gold_hits_path = gold_hits_path
        self.pred_path = pred_path
        self.synfile_map_path = synfile_map_path
        self.synfile_type_map_path = synfile_type_map_path
        self.type_to_ontology = type_to_ontology
        
        with open(id_map_path, 'r') as f:
            self.id_map = json.load(f)
        self.all_ids = {uid for ids in self.id_map.values() for uid in ids}
        
        self._reset()

    def _reset(self):
        self.gold_iter = HitsProcessor(
            hits_path=self.gold_hits_path,
            synfile_map=None,
            synfile_type_map=None,
            type_to_ontology=self.type_to_ontology
        ).read_articles(
            source=ArticleSource.GOLD,
            remove_sent_id_prefix=False,
            sort=True
        )
        self.hits_iter = HitsProcessor(
            hits_path=self.pred_path,
            synfile_map=self.synfile_map_path,
            synfile_type_map=self.synfile_type_map_path,
            type_to_ontology=self.type_to_ontology
        ).read_articles(source=ArticleSource.SYSTEM,
                        sort=True, 
                        print_summary=True)

        self.global_stat = Stat('global')
        self.per_type_stats: dict[str, Stat] = {}
        self.fn_counts = Counter()
        self.fp_counts = Counter()
        self.concept_mismatches = 0
        self.fp_instances = []
        self.fn_instances = []
        self.concept_mismatch_instances = []

    @staticmethod
    def group_by_sentence(articles: Iterator[ArticleRecord]) -> dict[str, list[CandidateHit]]:
        flat = defaultdict(list)
        for article in articles:
            for hit in article.resolved_hits:
                flat[hit.sentence_id].append(hit)
        return flat

    @staticmethod
    def _match_sentence(gold_hits, pred_hits, match_func):
        claimed_golds: set[int] = set()
        claimed_preds: set[int] = set()
        tp_pairs = []

        for i, pred_hit in enumerate(pred_hits):
            best_j, best_score = -1, 0
            for j, gold_hit in enumerate(gold_hits):
                if j in claimed_golds:
                    continue
                s = match_func(gold_hit, pred_hit)
                if s > best_score:
                    best_score, best_j = s, j
            if best_j >= 0:
                claimed_preds.add(i)
                claimed_golds.add(best_j)
                tp_pairs.append((pred_hit, gold_hits[best_j]))

        fn_golds = [g for i, g in enumerate(gold_hits) if i not in claimed_golds]
        fp_preds = [p for j, p in enumerate(pred_hits) if j not in claimed_preds]
        return tp_pairs, fp_preds, fn_golds

    def _concepts_match(self, pred_hit: CandidateHit, gold_hit: CandidateHit) -> bool:
        gold_id = gold_hit.entity_id
        if gold_id not in self.all_ids:
            return False
        return gold_id in self.id_map.get(pred_hit.entity_id, set())

    def _gold_type(self, gold_hit: CandidateHit) -> str:
        return getattr(gold_hit, 'mention_type', 'UNKNOWN')

    def _stat_for(self, name: str) -> Stat:
        if name not in self.per_type_stats:
            self.per_type_stats[name] = Stat(name)
        return self.per_type_stats[name]

    def _score(self,
               tp_pairs: Iterator[tuple[CandidateHit, CandidateHit]], 
               fp_preds: Iterator[CandidateHit], 
               fn_golds: Iterator[CandidateHit],
               track: str):
        if track not in ('recognition', 'normalization'):
            raise RuntimeError(f'Unknown track: {track}')

        for pred_hit, gold_hit in tp_pairs:
            if track == 'normalization' and not self._concepts_match(pred_hit, gold_hit):
                self.concept_mismatches += 1
                self.global_stat.inc_fp()
                self.global_stat.inc_fn()

                self.concept_mismatch_instances.append({
                    "sentence_id": gold_hit.sentence_id,
                    "span": [
                        gold_hit.start_position, _end(gold_hit.start_position, gold_hit.hit_length)
                    ],
                    "matched_text": pred_hit.raw_text,
                    "predicted_synonym": pred_hit.synonym,
                    "predicted_entity_id": pred_hit.entity_id,
                    "gold_synonym": gold_hit.raw_text,
                    "gold_entity_id": gold_hit.entity_id,
                })
            else:
                self.global_stat.inc_tp()
                self._stat_for(self._gold_type(gold_hit)).inc_tp()

        for p in fp_preds:
            self.global_stat.inc_fp()
            self.fp_counts[p.raw_text] += 1
            self.fp_instances.append({
                "sentence_id": p.sentence_id,
                "span": [p.start_position, _end(p.start_position, p.hit_length)],
                "matched_text": p.raw_text,
                "predicted_synonym": p.synonym,
                "predicted_entity_id": p.entity_id,
            })

        for g in fn_golds:
            self.global_stat.inc_fn()
            self.fn_counts[g.raw_text] += 1
            self._stat_for(self._gold_type(g)).inc_fn()
            self.fn_instances.append({
                "sentence_id": g.sentence_id,
                "span": [g.start_position, _end(g.start_position, g.hit_length)],
                "matched_text": g.raw_text,
                "gold_synonym": g.raw_text,
                "gold_entity_id": g.entity_id,
            })


    def run(self, mode: str, track: str, top_n=10, report_dir: str | None =None):
        self._reset()
        gold_groups = self.group_by_sentence(self.gold_iter)
        pred_groups = self.group_by_sentence(self.hits_iter)
        all_sents = set(gold_groups) | set(pred_groups)
        match_func = exact_match if mode == 'exact' else overlap_match

        for sent in all_sents:
            tp, fp, fn = self._match_sentence(
                gold_groups.get(sent, []),
                pred_groups.get(sent, []),
                match_func,
            )
            self._score(tp, fp, fn, track)

        self.print_summary(mode, track, top_n)
        if report_dir is not None:
            self.write_reports(report_dir, mode, track)

    @staticmethod
    def _hit_to_report_row(hit: CandidateHit) -> dict:
        return {
            "sentence_id": getattr(hit, "sentence_id", ""),
            "span": [getattr(hit, "span_start", None), getattr(hit, "span_end", None)],
            "raw_text": getattr(hit, "raw_text", ""),
            "entity_id": getattr(hit, "entity_id", ""),
            "synonym": getattr(hit, "synonym", getattr(hit, "raw_text", "")),
        }

    
    def print_summary(self, mode, track, top_n):
        print(f'SUMMARY FOR: {mode}, {track}')
        self.global_stat.print_summary()
        if self.per_type_stats:
            print(f"{'Type':<25} {'TP':>6} {'FN':>6} {'Recall':>8}")
            for name, st in sorted(self.per_type_stats.items()):
                print(f"{str(name)[:25]:<25} {st.true_positives:>6d} {st.false_negatives:>6d} {st.calc_recall():>8.4f}")
        print('\nEXAMPLES: FALSE POSITIVES')
        fp_sum = 0
        fp_total = self.global_stat.false_positives
        fn_total = self.global_stat.false_negatives
        for s, c in self.fp_counts.most_common(top_n):
            print(f"{s}: {c}")
            fp_sum += c
        print(f'Accounting for {((fp_sum / fp_total) if fp_total else 0) * 100}% of false positives.')
        print('\nEXAMPLES: FALSE NEGATIVES')
        fn_sum = 0
        for s, c in self.fn_counts.most_common(top_n):
                    print(f"{s}: {c}")
                    fn_sum += c
        print(f'Accounting for {((fn_sum / fn_total) if fn_total else 0) * 100}% of false negatives.')
        
    def write_reports(self, output_dir: str, mode: str, track: str):
        outdir = Path(output_dir)
        outdir.mkdir(parents=True, exist_ok=True)

        fp_path = outdir / f"false_positives_{mode}_{track}.tsv"
        fn_path = outdir / f"false_negatives_{mode}_{track}.tsv"
        cm_path = outdir / f"concept_mismatches_{mode}_{track}.tsv"

        if self.fp_instances:
            with fp_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "sentence_id",
                        "span",
                        "matched_text",
                        "predicted_synonym",
                        "predicted_entity_id",
                    ],
                    delimiter="\t",
                )
                writer.writeheader()
                writer.writerows(self.fp_instances)

        if self.fn_instances:
            with fn_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "sentence_id",
                        "span",
                        "matched_text",
                        "gold_synonym",
                        "gold_entity_id",
                    ],
                    delimiter="\t",
                )
                writer.writeheader()
                writer.writerows(self.fn_instances)

        if self.concept_mismatch_instances:
            with cm_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "sentence_id",
                        "span",
                        "matched_text",
                        "predicted_synonym",
                        "predicted_entity_id",
                        "gold_synonym",
                        "gold_entity_id",
                    ],
                    delimiter="\t",
                )
                writer.writeheader()
                writer.writerows(self.concept_mismatch_instances)




disease_path = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/data/synonyms/final/disease.syn'
disease_abbrev_path = '/mnt/extstudtemp/mitsopoulos/Text-Mining/disease_abbreviations.syn'
sentences = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/validation/disease/NCBI_disease/processed_text/NCBItrainset_corpus.sent'
synonyms = {HitType.DISEASE: [disease_path]}
abbrevs = {HitType.DISEASE: [disease_abbrev_path]}
output_dir = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/validation/disease/NCBI_disease/out_hits_train_set'
output_name = 'output'
model_hits = '/mnt/raidbio2/extproj/projekte/textmining/mirnaTextmining/mirClassification/validation/disease/NCBI_disease/model_hits/NCBItrainset_corpus.hits'
mapping = '/mnt/extstudtemp/mitsopoulos/Text-Mining/disease_mapping.json'
worchar = '.,'

MONDO_OBO_PATH = "/mnt/raidbio2/extstud/studtemp/mitsopoulos/ontologies/diseases/mondo_disease_ontology.obo"
#DOID_OBO_PATH = "/mnt/raidbio2/extstud/studtemp/mitsopoulos/ontologies/diseases/human_disease_ontology.obo"

disease_graph = OntologyGraph.from_obo(MONDO_OBO_PATH)
type_to_disease = {HitType.DISEASE: disease_graph}

res = run_syngrep(sentence_pattern=sentences,
            synonyms=synonyms,
            #abbrev_synonyms=abbrevs,
            output_dir=output_dir,
            output_name=output_name,
            abbrev=True, word_char=worchar
            )
# 37
test = Test(gold_hits_path=model_hits, 
            pred_path=res.hits_path,
            synfile_map_path=res.synfile_map_path, 
            synfile_type_map_path=res.synfile_type_map_path,
            id_map_path=mapping,
            type_to_ontology=type_to_disease)

test.run('overlap', 'recognition', top_n=15, report_dir='validation_report')
