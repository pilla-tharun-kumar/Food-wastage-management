"""Saved KNN model: relative sales patterns scaled to the caller's recent demand."""
from functools import lru_cache
from pathlib import Path
import json
import math

MODEL_DIR = Path(__file__).resolve().parent.parent / 'models'
MODEL_PATH = MODEL_DIR / 'demand_knn.joblib'


def features(values, weekday):
    import numpy as np
    values = np.asarray(values[-28:], dtype=float)
    scale = max(float(values.mean()), 0.001)
    normalized = values / scale
    vector = list(normalized[-14:]) + [float(normalized[-7:].mean()), float(normalized.std()),
                                      math.sin(2*math.pi*weekday/7), math.cos(2*math.pi*weekday/7)]
    return vector, scale


@lru_cache(maxsize=2)
def _load(modified):
    import joblib
    # Only load the locally trained, fixed model path; never accept uploaded pickle files.
    return joblib.load(MODEL_PATH)


def predict(rows, horizon=7):
    from .core import ForecastError
    if not MODEL_PATH.exists():
        raise ForecastError('Train the saved KNN model first: python -m forecasting.train_knn')
    if len(rows) < 28:
        raise ForecastError('KNN requires at least 28 consecutive history days.')
    if horizon != 7:
        raise ForecastError('The saved KNN model predicts a seven-day horizon.')
    try:
        model = _load(MODEL_PATH.stat().st_mtime_ns)
        vector, scale = features([row['sales'] for row in rows], (rows[-1]['date'].weekday()+1)%7)
        return [max(0.0, float(value)*scale) for value in model.predict([vector])[0]]
    except (ImportError, OSError) as exc:
        raise ForecastError('Install requirements-knn.txt and train the KNN model.') from exc


def metadata():
    path = MODEL_DIR / 'demand_knn_metrics.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'status': 'not_trained'}
