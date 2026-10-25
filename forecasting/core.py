"""Demand forecasts and decision support; no tenant data is stored in this module."""

from datetime import date, timedelta
from importlib.util import find_spec
from math import isfinite


class ForecastError(ValueError):
    pass


class ModelUnavailable(ForecastError):
    pass


def prepare_series(rows):
    """Require explicit daily records, including zero-sales days; missing is not zero."""
    if not isinstance(rows, list) or len(rows) < 21:
        raise ForecastError('At least 21 daily observations are required.')
    prepared = []
    for row in rows:
        try:
            day = date.fromisoformat(str(row['date']))
            values = {key: float(row.get(key, 0)) for key in ('sales', 'purchases', 'waste')}
        except (KeyError, TypeError, ValueError) as exc:
            raise ForecastError('Each row needs an ISO date and numeric sales, purchases and waste.') from exc
        if any(not isfinite(value) or value < 0 for value in values.values()):
            raise ForecastError('Historical quantities must be finite and nonnegative.')
        prepared.append({'date': day, **values})
    prepared.sort(key=lambda row: row['date'])
    if any(right['date'] - left['date'] != timedelta(days=1)
           for left, right in zip(prepared, prepared[1:])):
        raise ForecastError('Daily observations must be continuous, without missing or duplicate dates.')
    return prepared


def _seasonal(rows, horizon):
    values = [row['sales'] for row in rows]
    recent = sum(values[-7:]) / 7
    previous = sum(values[-14:-7]) / 7
    trend = max(0.7, min(1.3, recent / previous)) if previous else 1.0
    result = []
    for step in range(1, horizon + 1):
        target = rows[-1]['date'] + timedelta(days=step)
        same_weekday = [row['sales'] for row in rows[-28:] if row['date'].weekday() == target.weekday()]
        seasonal = sum(same_weekday) / len(same_weekday) if same_weekday else recent
        result.append(max(0.0, 0.75 * seasonal * trend + 0.25 * recent))
    return result


def _prophet(rows, horizon):
    from pandas import DataFrame
    from prophet import Prophet

    frame = DataFrame({'ds': [row['date'] for row in rows], 'y': [row['sales'] for row in rows]})
    model = Prophet(weekly_seasonality=True, daily_seasonality=False,
                    yearly_seasonality=False, uncertainty_samples=0)
    model.fit(frame)
    future = DataFrame({'ds': [rows[-1]['date'] + timedelta(days=i) for i in range(1, horizon + 1)]})
    return [max(0.0, float(value)) for value in model.predict(future)['yhat']]


def _lstm(rows, horizon):
    import torch
    from torch import nn

    torch.manual_seed(7)
    torch.set_num_threads(1)
    window = 14
    values = [row['sales'] for row in rows]
    scale = max(max(values), 1.0)
    normalized = [value / scale for value in values]
    inputs = torch.tensor([normalized[i:i + window] for i in range(len(values) - window)], dtype=torch.float32).unsqueeze(-1)
    targets = torch.tensor(normalized[window:], dtype=torch.float32).unsqueeze(-1)

    class Network(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(input_size=1, hidden_size=12, batch_first=True)
            self.head = nn.Linear(12, 1)

        def forward(self, data):
            output, _ = self.lstm(data)
            return self.head(output[:, -1, :])

    model = Network()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
    for _ in range(80):
        optimizer.zero_grad()
        loss = nn.functional.mse_loss(model(inputs), targets)
        loss.backward()
        optimizer.step()
    model.eval()
    context = normalized[-window:]
    result = []
    with torch.no_grad():
        for _ in range(horizon):
            prediction = max(0.0, float(model(torch.tensor(context[-window:], dtype=torch.float32).reshape(1, window, 1))))
            result.append(prediction * scale)
            context.append(prediction)
    return result


MODELS = {'seasonal': (_seasonal, 21), 'prophet': (_prophet, 28), 'lstm': (_lstm, 56)}

from .knn import predict as _knn
MODELS['knn'] = (_knn, 28)


def forecast(rows, horizon=7, model='auto'):
    prepared = prepare_series(rows)
    if not 1 <= horizon <= 30:
        raise ForecastError('Forecast horizon must be between 1 and 30 days.')
    if model not in (*MODELS, 'auto'):
        raise ForecastError('Model must be auto, seasonal, prophet, lstm or knn.')
    candidates = [model] if model != 'auto' else ['seasonal', 'lstm']
    errors = {}
    tested = []
    for name in candidates:
        method, minimum = MODELS[name]
        if len(prepared) < minimum + 7:
            if name in ('seasonal', 'knn') and len(prepared) >= minimum:
                pass  # A short series still permits a seasonal forecast without backtesting.
            else:
                errors[name] = f'{minimum + 7} days are required to backtest {name}.'
                continue
        if name == 'prophet' and (find_spec('prophet') is None or find_spec('pandas') is None):
            errors[name] = 'Install Prophet and pandas to train this model.'
            continue
        if name == 'lstm' and find_spec('torch') is None:
            errors[name] = 'Install PyTorch to train this model.'
            continue
        try:
            if len(prepared) >= minimum + 7:
                validation = method(prepared[:-7], 7)
                mae = sum(abs(predicted - actual['sales']) for predicted, actual in zip(validation, prepared[-7:])) / 7
            else:
                mae = None
            tested.append((name, mae, method))
        except Exception as exc:
            if model != 'auto':
                raise ForecastError(f'{name} could not be trained: {exc}') from exc
            errors[name] = f'Training failed: {type(exc).__name__}.'
    if not tested:
        raise ModelUnavailable(errors.get(model) or 'No forecasting model is available for this history.')
    selected, mae, method = min(tested, key=lambda item: float('inf') if item[1] is None else item[1])
    values = method(prepared, horizon)
    return {'model': selected, 'history_days': len(prepared), 'backtest_mae': round(mae, 3) if mae is not None else None,
            'weekly_total': round(sum(round(value, 3) for value in values[:7]), 3),
            'daily': [{'date': (prepared[-1]['date'] + timedelta(days=i)).isoformat(),
                       'quantity': round(max(0.0, value), 3)} for i, value in enumerate(values, start=1)],
            'models_skipped': errors}


def score(stock, days_to_expiry, daily_forecast, storage_capacity=None, lead_days=3, safety_days=2):
    stock = float(stock)
    quantities = [float(value) for value in daily_forecast]
    if stock < 0 or not isfinite(stock) or not quantities or any(value < 0 or not isfinite(value) for value in quantities):
        raise ForecastError('Stock and forecast quantities must be finite and nonnegative.')
    if storage_capacity is not None and (float(storage_capacity) < 0 or not isfinite(float(storage_capacity))):
        raise ForecastError('Storage capacity must be finite and nonnegative.')
    if not 0 <= lead_days <= 30 or not 0 <= safety_days <= 30:
        raise ForecastError('Lead and safety days must be between 0 and 30.')
    daily = sum(quantities[:7]) / min(7, len(quantities))
    days_usable = max(days_to_expiry + 1, 0) if days_to_expiry is not None else 30
    surplus = min(stock, max(0.0, stock - daily * days_usable))
    if stock == 0:
        risk = 0
    elif days_to_expiry is not None and days_to_expiry < 0:
        risk = 100
    else:
        surplus_ratio = surplus / stock
        urgency = 0 if days_to_expiry is None else max(0.0, 1 - days_to_expiry / 14)
        cover = min(1.0, stock / max(daily * 7, 0.001))
        risk = round(100 * (0.55 * surplus_ratio + 0.25 * urgency + 0.20 * cover))
    level = 'high' if risk >= 70 else 'medium' if risk >= 40 else 'low'
    needed = max(0.0, daily * (lead_days + safety_days) - stock)
    if storage_capacity is None:
        reorder = None
    else:
        reorder = min(needed, max(0.0, float(storage_capacity) - stock))
        if risk >= 70:
            reorder = 0.0
    return {'risk_score': risk, 'risk_level': level, 'expected_surplus': round(surplus, 3),
            'reorder_quantity': None if reorder is None else round(reorder, 3),
            'daily_demand': round(daily, 3), 'forecast_7d': round(sum(quantities[:7]), 3)}
