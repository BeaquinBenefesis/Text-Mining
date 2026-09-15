"""Unit tests for EvidenceAggregator propagation and AssociationEvidence bucketing
(design notes §5.2, §5.3).

Run from the repo root:  python -m unittest discover -s tests -v

Toy is_a DAG (internal ids T:x; co-occurrences carry external ids T_x):

        R
       / \\
      A   D
     / \\
    B   C
     \\ /
      M          M has two parents (diamond)

Descendant counts incl. self (N = 6): R 6, A 4, B 2, C 2, D 1, M 1
IC = -ln(count / 6): R 0, A ln 1.5, B ln 3, C ln 3, D ln 6, M ln 6
"""
import logging
import math
import unittest
from unittest import mock

from textmining.analysis import EvidenceAggregator
from textmining.enums import HitType
from textmining.models import CoOccurence
from textmining.ontology import OntologyGraph

T = HitType
MIR, TERM = T.MIR, T.DISEASE

IC = {'R': 0.0, 'A': math.log(1.5), 'B': math.log(3), 'C': math.log(3), 'D': math.log(6), 'M': math.log(6)}


def toy_graph():
    edges = [('A', 'R'), ('D', 'R'), ('B', 'A'), ('C', 'A'), ('M', 'B'), ('M', 'C')]
    return OntologyGraph.from_dict([(f'T:{c}', f'T:{p}', 'is_a') for c, p in edges],
                                   {f'T:{n}': {} for n in 'RABCDM'})


def cooc(term, epoch=0, mir='MIMAT1', section='1'):
    return CoOccurence(article_id=f'art{epoch}', sentence_id=f'art{epoch}.1.1', section_num=section,
                       origin_file_name=None, article_epoch=epoch,
                       normalized_ids=(mir, f'T_{term}'), entity_types=(MIR, TERM),
                       entity_positions=((0, 3), (10, 20)))


def article_score(*article_sums):
    """Final score for per-article sums: log2(1 + sum_a log2(1 + s_a))."""
    return math.log2(1 + sum(math.log2(1 + s) for s in article_sums))


class PropagationTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        logging.disable(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)

    def setUp(self):
        self.graph = toy_graph()
        self.agg = EvidenceAggregator({TERM: self.graph})

    def record(self, *coocs):
        for c in coocs:
            self.agg.record_coccurrence(c)

    def score(self, term, mir='MIMAT1'):
        return self.agg.associations[(mir, f'T_{term}')].score

    def targets(self, term):
        return dict(self.agg._cache[(f'T_{term}', TERM)])


class TestTargets(PropagationTestCase):

    def test_ic_values_of_toy_graph(self):
        for node, expected in IC.items():
            self.assertAlmostEqual(abs(self.graph.compute_ic(f'T:{node}')), expected)

    def test_term_itself_has_weight_one(self):
        self.record(cooc('M'))
        self.assertEqual(self.targets('M')['T_M'], 1)

    def test_ancestor_decay_is_ic_ratio(self):
        self.record(cooc('M'))
        t = self.targets('M')
        self.assertAlmostEqual(t['T_B'], IC['B'] / IC['M'])
        self.assertAlmostEqual(t['T_C'], IC['C'] / IC['M'])
        self.assertAlmostEqual(t['T_A'], IC['A'] / IC['M'])

    def test_zero_decay_root_is_not_a_target(self):
        self.record(cooc('M'))
        self.assertNotIn('T_R', self.targets('M'))
        self.assertNotIn(('MIMAT1', 'T_R'), self.agg.associations)

    def test_diamond_ancestor_receives_one_contribution(self):
        """A is reachable from M via B and via C; closure, not paths."""
        self.record(cooc('M'))
        self.assertEqual(sorted(self.targets('M')), ['T_A', 'T_B', 'T_C', 'T_M'])
        self.assertAlmostEqual(self.score('A'), article_score(IC['A'] / IC['M']))

    def test_direct_hit_on_root(self):
        self.record(cooc('R'))
        self.assertEqual(self.targets('R'), {'T_R': 1})
        self.assertAlmostEqual(self.score('R'), article_score(1))

    def test_unrelated_branch_untouched(self):
        self.record(cooc('M'))
        self.assertNotIn(('MIMAT1', 'T_D'), self.agg.associations)

    def test_targets_computed_once_per_term(self):
        with mock.patch.object(self.graph, 'ancestors', wraps=self.graph.ancestors) as spy:
            self.record(cooc('M', 0), cooc('M', 0), cooc('M', 1, mir='MIMAT2'))
        self.assertEqual(spy.call_count, 1)

    def test_unknown_term_raises(self):
        with self.assertRaises(ValueError):
            self.record(cooc('UNKNOWN'))


class TestAssociations(PropagationTestCase):

    def test_ancestor_association_keys_and_types(self):
        self.record(cooc('M'))
        self.assertEqual(set(self.agg.associations),
                         {('MIMAT1', 'T_M'), ('MIMAT1', 'T_B'), ('MIMAT1', 'T_C'), ('MIMAT1', 'T_A')})
        for key, assoc in self.agg.associations.items():
            self.assertEqual(assoc.normalized_ids, key)
            self.assertEqual(assoc.entity_types, (MIR, TERM))

    def test_mirnas_do_not_share_associations(self):
        self.record(cooc('B', mir='MIMAT1'), cooc('B', mir='MIMAT2'))
        self.assertAlmostEqual(self.score('B', 'MIMAT1'), article_score(1))
        self.assertAlmostEqual(self.score('B', 'MIMAT2'), article_score(1))


class TestArticleBuckets(PropagationTestCase):

    def test_same_article_is_compressed_once(self):
        self.record(cooc('B', 0), cooc('B', 0))
        self.assertAlmostEqual(self.score('B'), article_score(2))

    def test_different_articles_are_compressed_separately(self):
        self.record(cooc('B', 0), cooc('B', 1))
        self.assertAlmostEqual(self.score('B'), article_score(1, 1))

    def test_propagation_lands_before_the_log(self):
        """Section 5.2: two subtypes in one article pay into the ancestor's single bucket."""
        self.record(cooc('B', 0), cooc('C', 0))
        d_b, d_c = IC['A'] / IC['B'], IC['A'] / IC['C']
        self.assertAlmostEqual(self.score('A'), article_score(d_b + d_c))
        self.assertNotAlmostEqual(self.score('A'), math.log2(1 + math.log2(1 + d_b) + math.log2(1 + d_c)))

    def test_direct_and_propagated_share_a_bucket(self):
        self.record(cooc('A', 0), cooc('B', 0))
        self.assertAlmostEqual(self.score('A'), article_score(1 + IC['A'] / IC['B']))

    def test_ancestor_only_in_later_article(self):
        self.record(cooc('A', 0), cooc('B', 1))
        self.assertAlmostEqual(self.score('A'), article_score(1, IC['A'] / IC['B']))

    def test_section_weight_multiplies_every_target(self):
        with mock.patch('textmining.models.section_weigth', return_value=3):
            self.record(cooc('B', 0))
        self.assertAlmostEqual(self.score('B'), article_score(3))
        self.assertAlmostEqual(self.score('A'), article_score(3 * IC['A'] / IC['B']))

    def test_reordered_stream_raises(self):
        self.record(cooc('B', 5))
        with self.assertRaises(ValueError):
            self.record(cooc('B', 4))


class TestPropagationSwitch(PropagationTestCase):

    def test_direct_only_records_no_ancestors(self):
        agg = EvidenceAggregator({}, propagate=False)          # no graph needed
        for c in (cooc('M', 0), cooc('B', 0), cooc('M', 1)):
            agg.record_coccurrence(c)
        self.assertEqual(set(agg.associations), {('MIMAT1', 'T_M'), ('MIMAT1', 'T_B')})
        self.assertAlmostEqual(agg.associations[('MIMAT1', 'T_M')].score, article_score(1, 1))
        self.assertAlmostEqual(agg.associations[('MIMAT1', 'T_B')].score, article_score(1))

    def test_direct_only_accepts_unknown_terms(self):
        agg = EvidenceAggregator({}, propagate=False)
        agg.record_coccurrence(cooc('UNKNOWN'))
        self.assertIn(('MIMAT1', 'T_UNKNOWN'), agg.associations)

    def test_direct_scores_do_not_depend_on_the_switch_without_shared_ancestry(self):
        """B's own score is unchanged by propagation when nothing below B is mentioned."""
        on = EvidenceAggregator({TERM: self.graph}, propagate=True)
        off = EvidenceAggregator({}, propagate=False)
        for c in (cooc('B', 0), cooc('D', 1), cooc('B', 2)):
            on.record_coccurrence(c); off.record_coccurrence(c)
        for key in off.associations:
            self.assertAlmostEqual(on.associations[key].score, off.associations[key].score)


if __name__ == '__main__':
    unittest.main()
