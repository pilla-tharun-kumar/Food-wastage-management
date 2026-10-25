import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from fastapi import HTTPException
from prediction_service.app import AnalysisInput, BatchInput, ScoreInput, analyze, analyze_batch, score_on_demand


class ServiceTests(unittest.TestCase):
    def payload(self):
        return {'history': [{'date': (date(2026, 10, 24) - timedelta(days=34-i)).isoformat(),
                             'sales': 3, 'purchases': 4, 'waste': 1} for i in range(35)],
                'stock': 40, 'days_to_expiry': 1, 'storage_capacity': 50, 'model': 'seasonal'}

    @patch.dict(os.environ, {'PREDICTION_SERVICE_TOKEN': 'test-token'})
    def test_token_and_analysis(self):
        body = AnalysisInput(**self.payload())
        with self.assertRaises(HTTPException) as error:
            analyze(body, None)
        self.assertEqual(error.exception.status_code, 401)
        result = analyze(body, 'test-token')
        self.assertEqual(len(result['forecast']['daily']), 7)
        self.assertEqual(result['score']['risk_level'], 'high')

    @patch.dict(os.environ, {'PREDICTION_SERVICE_TOKEN': ''})
    def test_batch_preserves_valid_results_and_reports_bad_series(self):
        good = dict(self.payload(), product_id='A')
        bad = dict(self.payload(), product_id='B')
        bad['history'] = bad['history'][:-1] + [bad['history'][-2]]
        result = analyze_batch(BatchInput(items=[good, bad]), None)
        self.assertIn('result', result['results'][0])
        self.assertIn('error', result['results'][1])

    @patch.dict(os.environ, {'PREDICTION_SERVICE_TOKEN': ''})
    def test_realtime_score_limits_reorder_and_rejects_nan(self):
        result = score_on_demand(ScoreInput(stock=1, daily_forecast=[4]*7, storage_capacity=3), None)
        self.assertEqual(result['reorder_quantity'], 2)
        with self.assertRaises(HTTPException):
            score_on_demand(ScoreInput(stock=1, daily_forecast=[float('nan')]*7), None)


if __name__ == '__main__':
    unittest.main()
