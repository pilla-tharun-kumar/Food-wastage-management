"""Bind to localhost; Django remains responsible for authentication and tenant scope."""

import os
from datetime import date
from typing import Literal
from secrets import compare_digest

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from forecasting.core import ForecastError, forecast, score


app = FastAPI(title='FoodBridge Prediction Service', version='1.0.0')


class DailyInput(BaseModel):
    date: date
    sales: float = Field(ge=0)
    purchases: float = Field(ge=0)
    waste: float = Field(ge=0)


class AnalysisInput(BaseModel):
    history: list[DailyInput] = Field(min_length=21, max_length=365)
    stock: float = Field(ge=0)
    days_to_expiry: int | None = None
    storage_capacity: float | None = Field(default=None, ge=0)
    lead_days: int = Field(default=3, ge=0, le=30)
    model: Literal['auto', 'seasonal', 'prophet', 'lstm', 'knn'] = 'seasonal'


class ScoreInput(BaseModel):
    stock: float = Field(ge=0, allow_inf_nan=False)
    days_to_expiry: int | None = None
    daily_forecast: list[float] = Field(min_length=7, max_length=30)
    storage_capacity: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    lead_days: int = Field(default=3, ge=0, le=30)


class BatchItem(AnalysisInput):
    product_id: str = Field(min_length=1, max_length=100)


class BatchInput(BaseModel):
    items: list[BatchItem] = Field(min_length=1, max_length=100)


def verify_token(x_service_token: str | None):
    expected = os.getenv('PREDICTION_SERVICE_TOKEN')
    if expected and not compare_digest(x_service_token or '', expected):
        raise HTTPException(status_code=401, detail='Invalid service token.')


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.post('/v1/analyze')
def analyze(body: AnalysisInput, x_service_token: str | None = Header(default=None)):
    verify_token(x_service_token)
    rows = [{'date': row.date.isoformat(), 'sales': row.sales,
             'purchases': row.purchases, 'waste': row.waste} for row in body.history]
    try:
        prediction = forecast(rows, model=body.model)
        decision = score(body.stock, body.days_to_expiry,
                         [point['quantity'] for point in prediction['daily']],
                         body.storage_capacity, body.lead_days)
    except ForecastError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {'forecast': prediction, 'score': decision}


@app.post('/v1/score')
def score_on_demand(body: ScoreInput, x_service_token: str | None = Header(default=None)):
    """Score changed stock instantly using an already generated demand forecast."""
    verify_token(x_service_token)
    try:
        return score(body.stock, body.days_to_expiry, body.daily_forecast,
                     body.storage_capacity, body.lead_days)
    except ForecastError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post('/v1/batch')
def analyze_batch(body: BatchInput, x_service_token: str | None = Header(default=None)):
    """Bounded batch endpoint usable by a trusted scheduler; returns per-item errors."""
    verify_token(x_service_token)
    ids = [item.product_id for item in body.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=422, detail='Batch product IDs must be unique.')
    results = []
    for item in body.items:
        try:
            results.append({'product_id': item.product_id, 'result': analyze(item, x_service_token)})
        except HTTPException as exc:
            results.append({'product_id': item.product_id, 'error': exc.detail})
    return {'results': results}
