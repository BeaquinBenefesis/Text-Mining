"""Unit tests for multi-relationship OntologyGraphs (design notes §13.2).

Run from the repo root:  python -m unittest discover -s tests -v

Toy anatomy, edges child -> parent:

    body                     root of the part_of + is_a hierarchy
      organ      is_a        body
      liver      is_a        organ
      lobule     part_of     liver
      hepatocyte part_of     lobule
      bud        develops_from liver   (never followed)
    other                    unrelated root
"""
import logging
import pickle
import unittest

from textmining.ontology import OntologyGraph, normalize_relationships

EDGES = [
    ('X:organ', 'X:body', 'is_a'),
    ('X:liver', 'X:organ', 'is_a'),
    ('X:lobule', 'X:liver', 'part_of'),
    ('X:hepatocyte', 'X:lobule', 'part_of'),
    ('X:bud', 'X:liver', 'develops_from'),
]
NODES = {n: {} for n in ('X:body', 'X:organ', 'X:liver', 'X:lobule', 'X:hepatocyte', 'X:bud', 'X:other')}


def graph(relationships='is_a', root_ids=None):
    g = OntologyGraph.from_dict(EDGES, dict(NODES), relationships)
    if root_ids is None:
        return g
    return OntologyGraph(g.graph.copy(), relationships, root_ids=root_ids)


def ancestor_ids(g, term):
    return sorted(g._rel_subgraph[i]['id'] for i in g.ancestors(g.map_to_index(term)))


class RelationshipTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        logging.disable(logging.CRITICAL)

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)


class TestNormalize(RelationshipTestCase):

    def test_string_is_one_relationship(self):
        self.assertEqual(normalize_relationships('is_a'), ('is_a',))

    def test_iterable_is_sorted_and_deduplicated(self):
        self.assertEqual(normalize_relationships(['part_of', 'is_a', 'part_of']), ('is_a', 'part_of'))

    def test_empty_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_relationships([])

    def test_graph_stores_normalized_tuple(self):
        self.assertEqual(graph(['part_of', 'is_a']).relationships, ('is_a', 'part_of'))
        self.assertEqual(graph('is_a').relationships, ('is_a',))


class TestHierarchy(RelationshipTestCase):

    def test_is_a_only_ignores_part_of(self):
        g = graph('is_a')
        self.assertEqual(ancestor_ids(g, 'X:hepatocyte'), [])
        self.assertEqual(ancestor_ids(g, 'X:liver'), ['X:body', 'X:organ'])

    def test_union_follows_both(self):
        g = graph(('is_a', 'part_of'))
        self.assertEqual(ancestor_ids(g, 'X:hepatocyte'), ['X:body', 'X:liver', 'X:lobule', 'X:organ'])

    def test_unlisted_relationship_is_never_followed(self):
        g = graph(('is_a', 'part_of'))
        self.assertEqual(ancestor_ids(g, 'X:bud'), [])

    def test_ic_uses_the_union(self):
        g = graph(('is_a', 'part_of'))
        # liver has lobule and hepatocyte below it only via part_of
        self.assertEqual(g._descendant_count_cache.get(g.map_to_index('X:liver')), None)
        g.compute_ic('X:liver')
        self.assertEqual(g._descendant_count_cache[g.map_to_index('X:liver')], 3)

    def test_lca_across_relationships(self):
        g = graph(('is_a', 'part_of'))
        self.assertEqual(g.find_lca('X:hepatocyte', 'X:organ'), 'X_organ')

    def test_parallel_edges_do_not_break_anything(self):
        edges = EDGES + [('X:lobule', 'X:liver', 'is_a')]    # same pair, second relationship
        g = OntologyGraph.from_dict(edges, dict(NODES), ('is_a', 'part_of'))
        self.assertEqual(ancestor_ids(g, 'X:hepatocyte'), ['X:body', 'X:liver', 'X:lobule', 'X:organ'])
        self.assertEqual(g._depths[g.map_to_index('X:hepatocyte')], 4)


class TestRootRestriction(RelationshipTestCase):

    def test_restriction_over_union_keeps_part_of_descendants(self):
        g = graph(('is_a', 'part_of'), root_ids=['X:body'])
        self.assertEqual(sorted(g._id_to_idx), ['X:body', 'X:hepatocyte', 'X:liver', 'X:lobule', 'X:organ'])
        self.assertEqual([g._rel_subgraph[i]['id'] for i in g.roots], ['X:body'])

    def test_restriction_over_is_a_drops_part_of_descendants(self):
        g = graph('is_a', root_ids=['X:body'])
        self.assertEqual(sorted(g._id_to_idx), ['X:body', 'X:liver', 'X:organ'])

    def test_unlisted_relationship_does_not_pull_in_nodes(self):
        g = graph(('is_a', 'part_of'), root_ids=['X:body'])
        self.assertNotIn('X:bud', g._id_to_idx)


class TestCacheIdentity(RelationshipTestCase):

    def test_built_with_compares_roots_and_relationships(self):
        g = graph(('is_a', 'part_of'), root_ids=['X_body'])
        self.assertTrue(g.built_with(['X:body'], ['part_of', 'is_a']))
        self.assertFalse(g.built_with(['X:body'], 'is_a'))
        self.assertFalse(g.built_with(None, ('is_a', 'part_of')))

    def test_old_pickle_defaults_to_is_a(self):
        g = graph('is_a')
        del g.__dict__['relationships']                     # as pickled before this change
        restored = pickle.loads(pickle.dumps(g))
        self.assertEqual(restored.relationships, ('is_a',))
        self.assertTrue(restored.built_with(None, 'is_a'))
        self.assertFalse(restored.built_with(None, ('is_a', 'part_of')))


if __name__ == '__main__':
    unittest.main()
