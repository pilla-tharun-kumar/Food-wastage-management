"""Use the FastAPI worker when configured, or the same core locally for development."""

import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .core import ForecastError, forecast, score


def analyze(rows, *, stock, days_to_expiry, storage_capacity, lead_days, model='auto'):
    payload = {'history': rows, 'stock': stock, 'days_to_expiry': days_to_expiry,
               'storage_capacity': storage_capacity, 'lead_days': lead_days, 'model': model}
    service_url = os.getenv('PREDICTION_SERVICE_URL', '').rstrip('/')
    if service_url:
        headers = {'Content-Type': 'application/json'}
        if os.getenv('PREDICTION_SERVICE_TOKEN'):
            headers['X-Service-Token'] = os.environ['PREDICTION_SERVICE_TOKEN']
        request = Request(f'{service_url}/v1/analyze', data=json.dumps(payload).encode(), headers=headers)
        try:
            with urlopen(request, timeout=120) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ForecastError(f'Prediction service unavailable: {exc}') from exc
    prediction = forecast(rows, model=model)
    decision = score(stock, days_to_expiry, [point['quantity'] for point in prediction['daily']],
                     storage_capacity, lead_days)
    return {'forecast': prediction, 'score': decision}
