"""Unit tests for HitProcessor._resolve_groups (see DISAMBIGUATION_DESIGN.md).

Run from the repo root:  python -m unittest discover -s tests -v
"""
import logging
import unittest

from textmining.article_utils import ArticleEvidence
from textmining.enums import GroupStatus, HitType, SynonymType
from textmining.hit_utils import HitProcessor, HitProcessorHistory
from textmining.models import CandidateHit, HitGroup
from textmining.ontology import OntologyGraph

T = HitType
STD = SynonymType.STANDARD
ABBR = SynonymType.ABBREVIATION
INFERRED = SynonymType.INFERRED_ABBREVIATION


def toy_graph(edges, nodes):
    """Ids in graphs are internal (GO:b); hits carry external ids (GO_b), as in the pipeline."""
    return OntologyGraph.from_dict([(child, parent, 'is_a') for child, parent in edges],
                                   {n: {} for n in nodes})


GRAPHS = {
    # GO:b and GO:c share GO:r; GO:x and GO:y have no common ancestor
    T.BIOLOGICAL_PROCESS: toy_graph([('GO:b', 'GO:r'), ('GO:c', 'GO:r')],
                                    ['GO:r', 'GO:b', 'GO:c', 'GO:x', 'GO:y']),
    T.PATHWAY: toy_graph([], ['PW:a']),
    T.DISEASE: toy_graph([('DIS:b', 'DIS:r'), ('DIS:c', 'DIS:r')], ['DIS:r', 'DIS:b', 'DIS:c', 'DIS:x', 'DIS:y']),
    T.TAXON: toy_graph([('TAX:b', 'TAX:r'), ('TAX:c', 'TAX:r')], ['TAX:r', 'TAX:b', 'TAX:c']),
    T.CELL: toy_graph([], ['CL:a']),
    T.TISSUE: toy_graph([], ['BTO:a']),
}


class StubMirNormalizer:
    """miRNA-shaped context = a suffix such as '-7' or '-21'."""
    def has_mirna_shaped_context(self, prefix, suffix):
        return bool(suffix) and suffix.startswith('-')


def make_processor(type_to_ontology=None):
    # __init__ parses syngrep map files; resolution only needs these three attributes
    p = HitProcessor.__new__(HitProcessor)
    p.type_to_ontology = GRAPHS if type_to_ontology is None else type_to_ontology
    p.mir_normalizer = StubMirNormalizer()
    p.history = HitProcessorHistory()
    return p


def hit(entity_type, entity_id, synonym_type=STD, suffix=None, synonym='syn'):
    return CandidateHit(entity_type=entity_type, synonym_type=synonym_type, sentence_id='100.1.1',
                        entity_id=entity_id, raw_text=synonym, start_position=10, hit_length=len(synonym),
                        suffix=suffix, synonym=synonym)


def group(*hits):
    g = HitGroup()
    for h in hits:
        g.add_hit(h)
    return g


class ResolveGroupsTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        logging.disable(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)

    def resolve(self, g, supported=(), processor=None):
        p = processor or make_processor()
        out = p._resolve_groups([g], ArticleEvidence(unambiguous_entity_ids=set(supported)))
        return out, p

    def assertEmitted(self, out, expected):
        self.assertCountEqual([(h.entity_type, h.entity_id) for h in out], expected)


class TestUnchangedPaths(ResolveGroupsTestCase):

    def test_exact_match(self):
        g = group(hit(T.DISEASE, 'DIS_b'))
        out, _ = self.resolve(g)
        self.assertEqual(g.group_status, GroupStatus.EXACT_MATCH)
        self.assertEmitted(out, [(T.DISEASE, 'DIS_b')])

    def test_single_abbreviation_supported(self):
        g = group(hit(T.DISEASE, 'DIS_b', ABBR))
        out, _ = self.resolve(g, supported={'DIS_b'})
        self.assertEqual(g.group_status, GroupStatus.RESOLVED)
        self.assertEmitted(out, [(T.DISEASE, 'DIS_b')])

    def test_single_abbreviation_unsupported_fails(self):
        g = group(hit(T.DISEASE, 'DIS_b', ABBR))
        out, _ = self.resolve(g)
        self.assertEqual(g.group_status, GroupStatus.FAILURE)
        self.assertEmitted(out, [])

    def test_standard_beats_unsupported_abbreviation(self):
        """'pig': TAXON standard hit, DISEASE abbreviation without support."""
        g = group(hit(T.TAXON, 'TAX_b'), hit(T.DISEASE, 'DIS_b', ABBR))
        out, _ = self.resolve(g)
        self.assertEqual(g.group_status, GroupStatus.RESOLVED)
        self.assertEmitted(out, [(T.TAXON, 'TAX_b')])

    def test_both_abbreviations_unsupported_fail(self):
        """'PD' with the acronym rule applied: both sides are abbreviations, no definition."""
        g = group(hit(T.CELL, 'CL_a', ABBR), hit(T.DISEASE, 'DIS_b', ABBR))
        out, _ = self.resolve(g)
        self.assertEqual(g.group_status, GroupStatus.FAILURE)
        self.assertEmitted(out, [])

    def test_inferred_abbreviation_suppresses_abbreviations_of_all_types(self):
        """'Parkinson's disease (PD)': the inferred DISEASE hit wins over abbreviation readings."""
        g = group(hit(T.CELL, 'CL_a', ABBR), hit(T.DISEASE, 'DIS_c', ABBR), hit(T.DISEASE, 'DIS_b', INFERRED))
        out, _ = self.resolve(g)
        self.assertEqual(g.group_status, GroupStatus.RESOLVED)
        self.assertEmitted(out, [(T.DISEASE, 'DIS_b')])


class TestSingleType(ResolveGroupsTestCase):

    def test_supported_id_wins(self):
        g = group(hit(T.DISEASE, 'DIS_b'), hit(T.DISEASE, 'DIS_c'))
        out, _ = self.resolve(g, supported={'DIS_c'})
        self.assertEqual(g.group_status, GroupStatus.RESOLVED)
        self.assertEmitted(out, [(T.DISEASE, 'DIS_c')])

    def test_lca_without_support(self):
        g = group(hit(T.DISEASE, 'DIS_b'), hit(T.DISEASE, 'DIS_c'))
        out, _ = self.resolve(g)
        self.assertEqual(g.group_status, GroupStatus.RESOLVED)
        self.assertEmitted(out, [(T.DISEASE, 'DIS_r')])

    def test_lca_when_several_ids_supported(self):
        g = group(hit(T.DISEASE, 'DIS_b'), hit(T.DISEASE, 'DIS_c'))
        out, _ = self.resolve(g, supported={'DIS_b', 'DIS_c'})
        self.assertEqual(g.group_status, GroupStatus.RESOLVED)
        self.assertEmitted(out, [(T.DISEASE, 'DIS_r')])

    def test_no_lca_is_ambiguous_id(self):
        g = group(hit(T.DISEASE, 'DIS_x'), hit(T.DISEASE, 'DIS_y'))
        out, _ = self.resolve(g)
        self.assertEqual(g.group_status, GroupStatus.AMBIGUOUS_ID)
        self.assertEmitted(out, [])

    def test_types_come_from_filtered_hits(self):
        """Two TAXON ids + an unsupported DISEASE abbreviation: survivors are one type (LCA),
        not an entity-type collision."""
        g = group(hit(T.TAXON, 'TAX_b'), hit(T.TAXON, 'TAX_c'), hit(T.DISEASE, 'DIS_b', ABBR))
        out, _ = self.resolve(g)
        self.assertEqual(g.group_status, GroupStatus.RESOLVED)
        self.assertEmitted(out, [(T.TAXON, 'TAX_r')])


class TestMultiType(ResolveGroupsTestCase):

    def test_both_types_emitted_without_support(self):
        """'Wnt signaling pathway' in PW and GO."""
        g = group(hit(T.PATHWAY, 'PW_a'), hit(T.BIOLOGICAL_PROCESS, 'GO_b'))
        out, _ = self.resolve(g)
        self.assertEqual(g.group_status, GroupStatus.RESOLVED_MULTI_TYPE)
        self.assertEmitted(out, [(T.PATHWAY, 'PW_a'), (T.BIOLOGICAL_PROCESS, 'GO_b')])

    def test_support_does_not_choose_between_types(self):
        g = group(hit(T.PATHWAY, 'PW_a'), hit(T.BIOLOGICAL_PROCESS, 'GO_b'))
        out, _ = self.resolve(g, supported={'GO_b'})
        self.assertEqual(g.group_status, GroupStatus.RESOLVED_MULTI_TYPE)
        self.assertEmitted(out, [(T.PATHWAY, 'PW_a'), (T.BIOLOGICAL_PROCESS, 'GO_b')])

    def test_cell_and_tissue(self):
        """'hepatocyte' in CL and BTO."""
        g = group(hit(T.CELL, 'CL_a'), hit(T.TISSUE, 'BTO_a'))
        out, _ = self.resolve(g)
        self.assertEqual(g.group_status, GroupStatus.RESOLVED_MULTI_TYPE)
        self.assertEmitted(out, [(T.CELL, 'CL_a'), (T.TISSUE, 'BTO_a')])

    def test_support_picks_within_a_type_part(self):
        g = group(hit(T.PATHWAY, 'PW_a'), hit(T.BIOLOGICAL_PROCESS, 'GO_b'), hit(T.BIOLOGICAL_PROCESS, 'GO_c'))
        out, _ = self.resolve(g, supported={'GO_c', 'PW_a'})
        self.assertEqual(g.group_status, GroupStatus.RESOLVED_MULTI_TYPE)
        self.assertEmitted(out, [(T.PATHWAY, 'PW_a'), (T.BIOLOGICAL_PROCESS, 'GO_c')])

    def test_parts_resolved_by_different_routes_are_fully_resolved(self):
        """PW by single id, GO by LCA: every part resolved."""
        g = group(hit(T.PATHWAY, 'PW_a'), hit(T.BIOLOGICAL_PROCESS, 'GO_b'), hit(T.BIOLOGICAL_PROCESS, 'GO_c'))
        out, _ = self.resolve(g)
        self.assertEqual(g.group_status, GroupStatus.RESOLVED_MULTI_TYPE)
        self.assertEmitted(out, [(T.PATHWAY, 'PW_a'), (T.BIOLOGICAL_PROCESS, 'GO_r')])

    def test_partially_resolved_emits_resolved_parts(self):
        g = group(hit(T.PATHWAY, 'PW_a'), hit(T.BIOLOGICAL_PROCESS, 'GO_x'), hit(T.BIOLOGICAL_PROCESS, 'GO_y'))
        out, _ = self.resolve(g)
        self.assertEqual(g.group_status, GroupStatus.PARTIALLY_RESOLVED)
        self.assertEmitted(out, [(T.PATHWAY, 'PW_a')])

    def test_every_part_failing_is_ambiguous_id(self):
        g = group(hit(T.DISEASE, 'DIS_x'), hit(T.DISEASE, 'DIS_y'),
                  hit(T.BIOLOGICAL_PROCESS, 'GO_x'), hit(T.BIOLOGICAL_PROCESS, 'GO_y'))
        out, _ = self.resolve(g)
        self.assertEqual(g.group_status, GroupStatus.AMBIGUOUS_ID)
        self.assertEmitted(out, [])

    def test_type_without_ontology_fails_only_its_part(self):
        graphs = {t: g for t, g in GRAPHS.items() if t is not T.TISSUE}
        g = group(hit(T.PATHWAY, 'PW_a'), hit(T.TISSUE, 'BTO_a'), hit(T.TISSUE, 'BTO_b'))
        out, _ = self.resolve(g, processor=make_processor(graphs))
        self.assertEqual(g.group_status, GroupStatus.PARTIALLY_RESOLVED)
        self.assertEmitted(out, [(T.PATHWAY, 'PW_a')])

    def test_split_hits_keep_their_span(self):
        g = group(hit(T.PATHWAY, 'PW_a'), hit(T.BIOLOGICAL_PROCESS, 'GO_b'))
        out, _ = self.resolve(g)
        self.assertEqual(len({(h.sentence_id, h.start_position, h.hit_length) for h in out}), 1)


class TestMirException(ResolveGroupsTestCase):

    def test_mir_without_context_is_not_split(self):
        """'bantam' without miRNA context."""
        g = group(hit(T.MIR, 'MIMAT1'), hit(T.TAXON, 'TAX_b'))
        out, _ = self.resolve(g)
        self.assertEqual(g.group_status, GroupStatus.AMBIGUOUS_ENTITY_TYPE)
        self.assertEmitted(out, [])

    def test_mir_with_context_wins(self):
        g = group(hit(T.MIR, 'MIMAT1', suffix='-7'), hit(T.TAXON, 'TAX_b'))
        out, _ = self.resolve(g)
        self.assertEqual(g.group_status, GroupStatus.RESOLVED)
        self.assertEmitted(out, [(T.MIR, 'MIMAT1')])

    def test_mir_collision_with_supported_other_type(self):
        g = group(hit(T.MIR, 'MIMAT1'), hit(T.TAXON, 'TAX_b'))
        out, _ = self.resolve(g, supported={'TAX_b'})
        self.assertEqual(g.group_status, GroupStatus.RESOLVED)
        self.assertEmitted(out, [(T.TAXON, 'TAX_b')])


class TestHistory(ResolveGroupsTestCase):

    def test_new_statuses_count_as_resolved(self):
        p = make_processor()
        groups = [
            group(hit(T.PATHWAY, 'PW_a', synonym='wnt'), hit(T.BIOLOGICAL_PROCESS, 'GO_b', synonym='wnt')),
            group(hit(T.PATHWAY, 'PW_a', synonym='mixed'), hit(T.BIOLOGICAL_PROCESS, 'GO_x', synonym='mixed'),
                  hit(T.BIOLOGICAL_PROCESS, 'GO_y', synonym='mixed')),
        ]
        out = p._resolve_groups(groups, ArticleEvidence())
        h = p.history
        self.assertEqual(h.output_hits, len(out))
        self.assertEqual(h.group_status_counts[GroupStatus.RESOLVED_MULTI_TYPE], 1)
        self.assertEqual(h.group_status_counts[GroupStatus.PARTIALLY_RESOLVED], 1)
        self.assertAlmostEqual(h.resolution_rate, 1.0)
        self.assertEqual(h.multi_candidate_resolved, 2)
        self.assertEqual(h.resolved_synonym_counts['wnt'], 1)
        self.assertEqual(h.resolved_synonym_counts['mixed'], 1)
        self.assertEqual(h.partially_resolved_synonym_counts['mixed'], 1)
        self.assertEqual(h.partially_resolved_synonym_counts['wnt'], 0)

    def test_emitted_hits_per_group(self):
        p = make_processor()
        groups = [
            group(hit(T.DISEASE, 'DIS_b')),                                           # exact: 1
            group(hit(T.PATHWAY, 'PW_a'), hit(T.BIOLOGICAL_PROCESS, 'GO_b')),         # split: 2
            group(hit(T.DISEASE, 'DIS_x'), hit(T.DISEASE, 'DIS_y')),                  # no LCA: 0
            group(hit(T.DISEASE, 'DIS_c', ABBR)),                                     # failure: 0
        ]
        out = p._resolve_groups(groups, ArticleEvidence())
        self.assertEqual(p.history.emitted_hits_per_group_counts, {1: 1, 2: 1, 0: 2})
        self.assertEqual(sum(n * c for n, c in p.history.emitted_hits_per_group_counts.items()), len(out))


if __name__ == '__main__':
    unittest.main()
