import csv
import io
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from forecasting.core import ForecastError, forecast, score
from inventory.models import (Business, Category, CategoryPredictionSnapshot, DemandObservation,
                              InventoryBatch, Membership, PredictionSnapshot, Product)
from inventory.prediction import HEADERS


def daily_rows(days=35, start=None):
    start = start or timezone.localdate() - timedelta(days=days)
    return [{'date': (start + timedelta(days=i)).isoformat(),
             'sales': 2 + (i % 7), 'purchases': 12 if i % 7 == 0 else 0,
             'waste': 0.1 if i % 7 == 6 else 0} for i in range(days)]


def upload(rows):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(HEADERS)
    writer.writerows(rows)
    return SimpleUploadedFile('demand.csv', stream.getvalue().encode('utf-8'), content_type='text/csv')


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PredictionAPITests(APITestCase):
    def setUp(self):
        self.business = Business.objects.create(name='Kitchen A')
        self.other = Business.objects.create(name='Kitchen B')
        self.user = get_user_model().objects.create_user('member', password='Testing-password-283!')
        self.outsider = get_user_model().objects.create_user('outsider', password='Testing-password-283!')
        Membership.objects.create(user=self.user, business=self.business)
        Membership.objects.create(user=self.outsider, business=self.other)
        category = Category.objects.get(code='vegetables')
        self.product = Product.objects.create(business=self.business, category=category, name='Tomatoes',
                                              sku='TOM-1', unit='kg', storage_capacity=Decimal('30'))
        self.second = Product.objects.create(business=self.business, category=category, name='Spinach',
                                             sku='SPN-1', unit='kg')
        self.foreign = Product.objects.create(business=self.other, category=category, name='Private',
                                              sku='TOM-1', unit='kg')
        self.client.force_authenticate(self.user)

    def history(self, product=None, days=35):
        product = product or self.product
        yesterday = timezone.localdate() - timedelta(days=1)
        DemandObservation.objects.bulk_create([
            DemandObservation(business=product.business, product=product, date=yesterday - timedelta(days=days-1-i),
                              sales_quantity=Decimal(str(2 + i % 7)), purchase_quantity=Decimal('10'),
                              waste_quantity=Decimal('0.1')) for i in range(days)])

    def test_import_rejects_foreign_sku_and_rolls_back_all_rows(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        response = self.client.post('/api/demand/import-csv/', {'file': upload([
            [yesterday, 'SPN-1', '2', '0', '0'], [yesterday, 'UNKNOWN', '1', '0', '0']])}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(DemandObservation.objects.count(), 0)

    def test_import_duplicate_requires_replace_and_preserves_other_dates(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        previous = yesterday - timedelta(days=1)
        self.history(days=1)
        data = [[previous, 'TOM-1', '4', '3', '0'], [yesterday, 'TOM-1', '5', '2', '1']]
        self.assertEqual(self.client.post('/api/demand/import-csv/', {'file': upload(data)}, format='multipart').status_code, 400)
        self.assertEqual(DemandObservation.objects.count(), 1)
        response = self.client.post('/api/demand/import-csv/?replace=true', {'file': upload(data)}, format='multipart')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['replaced'], 1)
        self.assertEqual(DemandObservation.objects.count(), 2)
        self.assertEqual(DemandObservation.objects.get(date=yesterday).sales_quantity, Decimal('5'))

    def test_history_and_predictions_are_tenant_scoped(self):
        self.history()
        self.history(self.foreign)
        self.assertEqual(self.client.get('/api/demand/coverage/').data['records'], 35)
        self.assertEqual(self.client.get('/api/demand/?product=%s' % self.foreign.pk).data['count'], 0)
        self.assertEqual(self.client.patch(f'/api/products/{self.foreign.pk}/planning/', {'storage_capacity': '100'}).status_code, 404)
        self.assertEqual(self.client.post('/api/predictions/run/', {'product': self.foreign.pk}).status_code, 400)
        response = self.client.post('/api/predictions/run/', {'product': self.product.pk, 'model': 'seasonal'})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['model_name'], 'seasonal')
        self.assertEqual(len(response.data['daily_forecast']), 7)
        self.assertEqual(PredictionSnapshot.objects.filter(business=self.business).count(), 1)
        self.assertEqual(self.client.get('/api/predictions/').data[0]['product'], self.product.pk)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(len(self.client.get('/api/predictions/').data), 0)

    def test_category_series_never_adds_unlike_units_or_missing_product_days(self):
        self.history()
        self.history(self.second, days=21)
        response = self.client.get('/api/demand/category-series/?category=vegetables&unit=kg')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['complete_days'], 21)
        self.assertEqual(response.data['daily'][-1]['sales'], 2 + (34 % 7) + 2 + (20 % 7))
        result = self.client.post('/api/predictions/run/', {'model': 'seasonal'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data['categories_updated'], 1)
        self.assertEqual(CategoryPredictionSnapshot.objects.filter(business=self.business).count(), 1)

    def test_prediction_requires_complete_recent_history(self):
        self.history(days=20)
        response = self.client.post('/api/predictions/run/', {'product': self.product.pk, 'model': 'seasonal'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PredictionSnapshot.objects.count(), 0)

    def test_malformed_product_filters_return_validation_error(self):
        self.assertEqual(self.client.get('/api/demand/?product=invalid').status_code, 400)
        self.assertEqual(self.client.post('/api/predictions/run/', {'product': 'invalid'}).status_code, 400)

    def test_planning_capacity_limits_reorder(self):
        self.history()
        InventoryBatch.objects.create(business=self.business, product=self.product, batch_number='B1',
                                      quantity=Decimal('1'), expiry_date=timezone.localdate() + timedelta(days=20))
        update = self.client.patch(f'/api/products/{self.product.pk}/planning/',
                                   {'storage_capacity': '4.000', 'reorder_lead_days': 3})
        self.assertEqual(update.status_code, 200, update.data)
        response = self.client.post('/api/predictions/run/', {'product': self.product.pk, 'model': 'seasonal'})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertLessEqual(Decimal(response.data['reorder_quantity']), Decimal('3'))


class ForecastCoreTests(APITestCase):
    def test_forecast_has_seven_nonnegative_dates_and_a_backtest(self):
        result = forecast(daily_rows(), model='seasonal')
        self.assertEqual(result['model'], 'seasonal')
        self.assertEqual(len(result['daily']), 7)
        self.assertIsNotNone(result['backtest_mae'])
        self.assertTrue(all(row['quantity'] >= 0 for row in result['daily']))

    def test_gaps_are_not_silently_treated_as_zero(self):
        rows = daily_rows()
        rows.pop(10)
        with self.assertRaises(ForecastError):
            forecast(rows)

    def test_high_surplus_near_expiry_blocks_reorder(self):
        result = score(100, 1, [2] * 7, storage_capacity=150, lead_days=3)
        self.assertEqual(result['risk_level'], 'high')
        self.assertEqual(result['reorder_quantity'], 0)
        self.assertGreater(result['expected_surplus'], 90)
