import unittest

from scripts.evaluate_clip_engine import _flatten_candidates, evaluate


class ClipEngineEvaluatorTests(unittest.TestCase):
    def test_ranking_metrics_use_one_to_one_temporal_matches(self):
        candidates=[
            {'source_start':0.,'source_end':10.,'score':90.},
            {'source_start':1.,'source_end':9.,'score':80.},
            {'source_start':20.,'source_end':30.,'score':70.},
        ]
        labels=[{'start':0.,'end':10.},{'start':20.,'end':30.}]
        result=evaluate(candidates,labels,top_k=2)
        self.assertEqual(result['precision_at_k'],.5)
        self.assertEqual(result['recall_at_k'],.5)
        self.assertEqual(result['matched_count'],1)
        self.assertEqual(result['temporal_duplicates'],1)
        self.assertEqual(result['mean_total_boundary_error_seconds'],0.)

    def test_result_cache_envelope_and_flat_candidates_are_supported(self):
        payload={'schema':1,'result':{'candidates':[
            {'source_start':2,'source_end':8,'score':75}]}}
        candidates=_flatten_candidates(payload)
        self.assertEqual(candidates[0]['source_start'],2.)
        result=evaluate(candidates,[{'start':2,'end':8}])
        self.assertEqual(result['precision_at_k'],1.)

    def test_empty_labels_do_not_invent_recall(self):
        result=evaluate([],[],top_k=5)
        self.assertIsNone(result['precision_at_k'])
        self.assertIsNone(result['recall_at_k'])
        self.assertIsNone(result['mean_total_boundary_error_seconds'])

    def test_invalid_ground_truth_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            evaluate([], [{'start':2,'end':1}])


if __name__=='__main__':
    unittest.main()
