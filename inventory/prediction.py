"""Tenant-scoped demand ingestion and daily prediction orchestration."""

import csv
import io
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from forecasting.client import analyze
from forecasting.core import ForecastError
from .models import (Business, CategoryPredictionSnapshot, DemandObservation, InventoryBatch,
                     PredictionSnapshot, Product)


HEADERS = ['date', 'sku', 'sales_quantity', 'purchase_quantity', 'waste_quantity']
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000


def _quantity(value, field, row_number):
    try:
        number = Decimal(value)
        if not number.is_finite() or number < 0 or number > Decimal('999999999.999') or number.as_tuple().exponent < -3:
            raise InvalidOperation
        return number
    except (InvalidOperation, TypeError):
        raise ValidationError({'file': f'Row {row_number}: {field} must be nonnegative with at most 3 decimals.'})


@transaction.atomic
def import_history(upload, business, replace=False):
    if upload.size > MAX_BYTES:
        raise ValidationError({'file': 'CSV must be 2 MB or smaller.'})
    try:
        text = upload.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValidationError({'file': 'CSV must use UTF-8 encoding.'})
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames != HEADERS:
        raise ValidationError({'file': f'Use exactly these columns: {", ".join(HEADERS)}.'})
    products = {product.sku: product for product in Product.objects.filter(business=business)}
    yesterday = timezone.localdate() - timedelta(days=1)
    seen = set()
    records = []
    for number, row in enumerate(reader, start=2):
        if number > MAX_ROWS + 1:
            raise ValidationError({'file': f'CSV cannot contain more than {MAX_ROWS} rows.'})
        if None in row or any(value is None for value in row.values()):
            raise ValidationError({'file': f'Row {number}: column count does not match the template.'})
        sku = row['sku'].strip()
        product = products.get(sku)
        if product is None:
            raise ValidationError({'file': f'Row {number}: SKU {sku!r} does not belong to this business.'})
        try:
            day = date.fromisoformat(row['date'].strip())
        except ValueError:
            raise ValidationError({'file': f'Row {number}: date must use YYYY-MM-DD.'})
        if day > yesterday:
            raise ValidationError({'file': f'Row {number}: use complete days through yesterday; today is still in progress.'})
        key = (product.id, day)
        if key in seen:
            raise ValidationError({'file': f'Row {number}: duplicate SKU and date in this file.'})
        seen.add(key)
        records.append(DemandObservation(
            business=business, product=product, date=day,
            sales_quantity=_quantity(row['sales_quantity'].strip(), 'sales_quantity', number),
            purchase_quantity=_quantity(row['purchase_quantity'].strip(), 'purchase_quantity', number),
            waste_quantity=_quantity(row['waste_quantity'].strip(), 'waste_quantity', number), source='csv'))
    if not records:
        raise ValidationError({'file': 'CSV contains no data rows.'})
    existing = DemandObservation.objects.filter(business=business, product_id__in={record.product_id for record in records},
                                                date__in={record.date for record in records})
    existing_ids = {record.pk: (record.product_id, record.date) for record in existing}
    existing_keys = set(existing_ids.values())
    collisions = [record for record in records if (record.product_id, record.date) in existing_keys]
    if collisions and not replace:
        raise ValidationError({'file': f'{len(collisions)} daily records already exist. Set replace=true to update them.'})
    if collisions:
        DemandObservation.objects.filter(pk__in=[pk for pk, key in existing_ids.items() if key in seen]).delete()
    DemandObservation.objects.bulk_create(records)
    return {'imported': len(records), 'replaced': len(collisions)}


def _history(product, as_of):
    observations = list(DemandObservation.objects.filter(product=product, business=product.business, date__lte=as_of)
                        .order_by('-date')[:365])
    observations.reverse()
    return [{'date': row.date.isoformat(), 'sales': float(row.sales_quantity),
             'purchases': float(row.purchase_quantity), 'waste': float(row.waste_quantity)} for row in observations]


def predict_product(product, *, model='seasonal', as_of=None):
    as_of = as_of or timezone.localdate() - timedelta(days=1)
    history = _history(product, as_of)
    if not history or history[-1]['date'] != as_of.isoformat():
        raise ForecastError('History must include a completed record for yesterday.')
    batches = InventoryBatch.objects.filter(product=product, business=product.business, quantity__gt=0)
    stock = batches.aggregate(total=Sum('quantity'))['total'] or Decimal('0')
    nearest = batches.order_by('expiry_date').values_list('expiry_date', flat=True).first()
    result = analyze(history, stock=float(stock), days_to_expiry=(nearest - timezone.localdate()).days if nearest else None,
                     storage_capacity=float(product.storage_capacity) if product.storage_capacity is not None else None,
                     lead_days=product.reorder_lead_days, model=model)
    prediction = result['forecast']
    decision = result['score']
    snapshot, _ = PredictionSnapshot.objects.update_or_create(
        business=product.business, product=product, as_of_date=as_of,
        defaults={'model_name': prediction['model'], 'history_days': prediction['history_days'],
                  'backtest_mae': prediction['backtest_mae'], 'daily_forecast': prediction['daily'],
                  'forecast_7d': Decimal(str(decision['forecast_7d'])), 'stock_quantity': stock,
                  'nearest_expiry_date': nearest, 'risk_score': decision['risk_score'],
                  'risk_level': decision['risk_level'], 'expected_surplus': Decimal(str(decision['expected_surplus'])),
                  'reorder_quantity': None if decision['reorder_quantity'] is None else Decimal(str(decision['reorder_quantity']))})
    return snapshot


def category_history(business, category, unit, as_of):
    products = list(Product.objects.filter(business=business, category=category, unit=unit).values_list('id', flat=True))
    if not products:
        return []
    observations = DemandObservation.objects.filter(business=business, product_id__in=products, date__lte=as_of,
                                                    date__gte=as_of - timedelta(days=364))
    grouped = {}
    for row in observations:
        value = grouped.setdefault(row.date, {'products': set(), 'sales': 0.0, 'purchases': 0.0, 'waste': 0.0})
        value['products'].add(row.product_id)
        value['sales'] += float(row.sales_quantity)
        value['purchases'] += float(row.purchase_quantity)
        value['waste'] += float(row.waste_quantity)
    return [{'date': day.isoformat(), 'sales': value['sales'], 'purchases': value['purchases'],
             'waste': value['waste']} for day, value in sorted(grouped.items()) if len(value['products']) == len(products)]


def predict_category(business, category, unit, *, model='seasonal', as_of=None):
    as_of = as_of or timezone.localdate() - timedelta(days=1)
    history = category_history(business, category, unit, as_of)
    if not history or history[-1]['date'] != as_of.isoformat():
        raise ForecastError('Complete category history must include yesterday for every product.')
    result = analyze(history, stock=0, days_to_expiry=None, storage_capacity=None, lead_days=3, model=model)
    prediction = result['forecast']
    snapshot, _ = CategoryPredictionSnapshot.objects.update_or_create(
        business=business, category_id=category, unit=unit, as_of_date=as_of,
        defaults={'model_name': prediction['model'], 'history_days': prediction['history_days'],
                  'backtest_mae': prediction['backtest_mae'], 'daily_forecast': prediction['daily'],
                  'forecast_7d': Decimal(str(sum(day['quantity'] for day in prediction['daily'][:7])))})
    return snapshot


def run_predictions(business=None, *, model='seasonal'):
    businesses = [business] if business else Business.objects.all()
    result = {'updated': [], 'skipped': [], 'categories_updated': 0}
    for company in businesses:
        for product in Product.objects.filter(business=company).select_related('business', 'category'):
            try:
                snapshot = predict_product(product, model=model)
                result['updated'].append({'product_id': product.id, 'prediction_id': snapshot.id})
            except ForecastError as exc:
                result['skipped'].append({'product_id': product.id, 'reason': str(exc)})
        groups = Product.objects.filter(business=company).order_by().values_list('category_id', 'unit').distinct()
        for category_id, unit in groups:
            try:
                predict_category(company, category_id, unit, model=model)
                result['categories_updated'] += 1
            except ForecastError:
                pass
    return result
