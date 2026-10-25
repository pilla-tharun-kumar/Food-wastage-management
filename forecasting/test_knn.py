import json
import unittest
from pathlib import Path
from unittest.mock import patch
from .core import forecast, ForecastError


class SavedKNNTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parent.parent/'examples/knn_sample.json'
        self.rows = json.loads(path.read_text(encoding='utf-8'))['history']

    def test_saved_model_predicts_without_fitting(self):
        with patch('sklearn.neighbors.KNeighborsRegressor.fit', side_effect=AssertionError('Must not fit at inference')):
            result = forecast(self.rows, model='knn')
        self.assertEqual(len(result['daily']), 7)
        self.assertTrue(all(point['quantity'] >= 0 for point in result['daily']))
        self.assertAlmostEqual(result['weekly_total'], sum(point['quantity'] for point in result['daily']), places=3)

    def test_rescales_to_local_units_and_rejects_short_history(self):
        expected = forecast(self.rows, model='knn')
        scaled = [dict(row, sales=row['sales']*10) for row in self.rows]
        actual = forecast(scaled, model='knn')
        for left, right in zip(expected['daily'], actual['daily']):
            self.assertAlmostEqual(left['quantity']*10, right['quantity'], delta=.006)
        with self.assertRaises(ForecastError):
            forecast(self.rows[:-1], model='knn')
