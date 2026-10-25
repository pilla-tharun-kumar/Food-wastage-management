"""Run the saved KNN artifact on the bundled held-out sample without retraining."""
import json
from pathlib import Path
from .client import analyze


def main():
    root = Path(__file__).resolve().parent.parent
    payload = json.loads((root/'examples/knn_sample.json').read_text(encoding='utf-8'))
    expected = json.loads((root/'examples/knn_sample_expected.json').read_text(encoding='utf-8'))
    result = analyze(payload.pop('history'), **payload)
    predicted = [point['quantity'] for point in result['forecast']['daily']]
    actual = expected['actual_next_7_days']
    result['sample_actual_next_7_days'] = actual
    result['sample_mae'] = sum(abs(a-b) for a,b in zip(actual,predicted))/7
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
