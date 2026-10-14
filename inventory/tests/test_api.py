import csv
import io
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient, APITestCase
from inventory.csv_import import HEADERS
from inventory.models import Business, Category, DonationLog, ExpiryAlert, InventoryBatch, Membership, Product, StockTransaction
from inventory.services import refresh_alerts
from inventory.tasks import refresh_expiry_alerts


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class InventoryAPITests(APITestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.business = Business.objects.create(name='Business One', expiry_alert_days=7)
        self.other = Business.objects.create(name='Business Two')
        self.user = get_user_model().objects.create_user('member', password='Testing-password-283!')
        self.outsider = get_user_model().objects.create_user('outsider', password='Testing-password-283!')
        Membership.objects.create(user=self.user, business=self.business)
        Membership.objects.create(user=self.outsider, business=self.other)
        self.category = Category.objects.get(code='vegetables')
        self.product = Product.objects.create(business=self.business, name='Tomatoes', sku='TOM-1', barcode='123456789', category=self.category, unit='kg')
        self.other_product = Product.objects.create(business=self.other, name='Private tomatoes', sku='TOM-1', barcode='123456789', category=self.category, unit='kg')
        self.client.force_authenticate(self.user)

    def payload(self, **overrides):
        values = {'product': self.product.pk, 'batch_number': 'B-001', 'quantity': '10.000',
                  'received_date': (self.today-timedelta(days=10)).isoformat(), 'expiry_date': (self.today+timedelta(days=5)).isoformat()}
        values.update(overrides)
        return values

    def batch(self, **overrides):
        response = self.client.post('/api/inventory/', self.payload(**overrides))
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def upload(self, rows, headers=HEADERS):
        stream=io.StringIO();writer=csv.writer(stream);writer.writerow(headers);writer.writerows(rows)
        return self.client.post('/api/inventory/import-csv/', {'file': SimpleUploadedFile('inventory.csv', stream.getvalue().encode(), content_type='text/csv')}, format='multipart')

    def csv_row(self, **overrides):
        row = dict(zip(HEADERS, ['Tomatoes','TOM-1','123456789','vegetables','kg','CSV-1','4.500',
                               self.today.isoformat(),(self.today+timedelta(days=3)).isoformat(),'Shelf A','','']))
        row.update(overrides)
        return [row[field] for field in HEADERS]

    def test_anonymous_and_unassigned_accounts_are_denied(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/inventory/').status_code, 401)
        user=get_user_model().objects.create_user('unassigned')
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get('/api/inventory/').status_code, 403)

    def test_create_read_update_delete_with_audit_history(self):
        batch=self.batch()
        self.assertEqual(batch['status'],'expiring')
        url=f"/api/inventory/{batch['id']}/"
        response=self.client.patch(url,{'quantity':'8.000','version':batch['version'],'notes':'Count corrected'})
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.data['version'],2)
        self.assertEqual(StockTransaction.objects.first().delta,Decimal('-2'))
        self.assertEqual(self.client.get(url).data['quantity'],'8.000')
        self.assertEqual(self.client.delete(url,{'version':2}).status_code,204)
        self.assertEqual(InventoryBatch.objects.count(),0)
        self.assertEqual(StockTransaction.objects.count(),3)
        self.assertIsNone(StockTransaction.objects.first().batch)
        self.assertEqual(StockTransaction.objects.first().snapshot['product'],'Tomatoes')

    def test_put_and_partial_update_validate_dates(self):
        batch=self.batch()
        url=f"/api/inventory/{batch['id']}/"
        payload=self.payload(quantity='7',version=batch['version'])
        self.assertEqual(self.client.put(url,payload).status_code,200)
        response=self.client.patch(url,{'received_date':(self.today+timedelta(days=8)).isoformat(),'version':2})
        self.assertEqual(response.status_code,400)

    def test_negative_quantity_invalid_dates_precision_and_duplicate_batch(self):
        for changes in [{'quantity':'-1'},{'quantity':'0.0001'},{'quantity':'1000000000'}, {'expiry_date':(self.today-timedelta(days=11)).isoformat()}, {'alert_days':366}, {'alert_days':-1}]:
            self.assertEqual(self.client.post('/api/inventory/',self.payload(**changes)).status_code,400,changes)
        self.batch()
        self.assertEqual(self.client.post('/api/inventory/',self.payload()).status_code,400)

    def test_batch_cannot_switch_product(self):
        batch=self.batch()
        second=Product.objects.create(business=self.business,name='Other',sku='OTHER',category=self.category)
        self.assertEqual(self.client.patch(f"/api/inventory/{batch['id']}/",{'product':second.id,'version':1}).status_code,400)

    def test_tenant_isolation_all_read_and_write_routes(self):
        batch=self.batch()
        self.client.post('/api/donations/',{'batch':batch['id'],'quantity':'1','recipient':'Kitchen'})
        self.client.force_authenticate(self.outsider)
        for endpoint in ['inventory','transactions','alerts','donations']:
            self.assertEqual(self.client.get(f'/api/{endpoint}/').data['count'],0,endpoint)
        self.assertEqual(self.client.get('/api/summary/').data['total_batches'],0)
        self.assertEqual(self.client.get(f'/api/products/{self.product.id}/').status_code,404)
        url=f"/api/inventory/{batch['id']}/"
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.client.patch(url,{'quantity':'2','version':1}).status_code,404)
        self.assertEqual(self.client.delete(url,{'version':1}).status_code,404)
        self.assertEqual(self.client.post(url+'adjust/',{'delta':'-1','reason':'Test'}).status_code,404)
        self.assertEqual(self.client.post('/api/inventory/',self.payload()).status_code,400)
        self.assertEqual(self.client.post('/api/donations/',{'batch':batch['id'],'quantity':'1','recipient':'Other'}).status_code,400)
        alert=ExpiryAlert.objects.get(batch_id=batch['id'])
        self.assertEqual(self.client.post(f'/api/alerts/{alert.id}/acknowledge/').status_code,404)

    def test_user_cannot_choose_business_through_payload(self):
        batch=self.batch(business=self.other.id)
        self.assertEqual(InventoryBatch.objects.get(pk=batch['id']).business,self.business)

    def test_expiry_boundaries_zero_stock_and_overrides(self):
        for days in [-1,0,7,8]:
            self.batch(batch_number=f'D{days}',expiry_date=(self.today+timedelta(days=days)).isoformat())
        self.batch(batch_number='ZERO',quantity='0')
        self.batch(batch_number='OVERRIDE',alert_days=1)
        response=self.client.get('/api/inventory/expiring/')
        self.assertEqual({b['batch_number'] for b in response.data['results']},{'D0','D7'})
        self.assertEqual(self.client.get('/api/inventory/expiring/?days=0').data['count'],1)
        self.assertEqual(self.client.get('/api/inventory/expiring/?days=8').data['count'],4)
        for value in ['-1','366','abc','1.5']:
            self.assertEqual(self.client.get(f'/api/inventory/expiring/?days={value}').status_code,400)

    def test_alerts_deduplicate_acknowledge_resolve_and_reopen(self):
        batch=self.batch()
        refresh_alerts(self.business);refresh_alerts(self.business)
        self.assertEqual(ExpiryAlert.objects.count(),1)
        alert=ExpiryAlert.objects.get()
        self.assertEqual(self.client.post(f'/api/alerts/{alert.id}/acknowledge/').status_code,200)
        self.assertEqual(self.client.get('/api/summary/').data['unread_alerts'],0)
        url=f"/api/inventory/{batch['id']}/"
        self.client.patch(url,{'quantity':'0','version':1})
        self.assertEqual(self.client.get('/api/alerts/').data['count'],0)
        self.client.patch(url,{'quantity':'3','version':2})
        self.assertEqual(self.client.get('/api/summary/').data['unread_alerts'],1)

    def test_alert_severity_changes_when_date_advances(self):
        self.batch(expiry_date=self.today.isoformat())
        with patch('django.utils.timezone.localdate',return_value=self.today+timedelta(days=1)):
            refresh_expiry_alerts.run()
        self.assertEqual(ExpiryAlert.objects.get().severity,'expired')

    def test_settings_threshold_and_batch_override(self):
        self.batch()
        self.batch(batch_number='OVERRIDE',alert_days=6)
        self.assertEqual(self.client.patch('/api/business/',{'expiry_alert_days':2}).status_code,200)
        self.assertEqual(self.client.get('/api/alerts/').data['count'],1)
        self.assertEqual(self.client.patch('/api/business/',{'expiry_alert_days':366}).status_code,400)
        self.client.patch('/api/business/',{'name':'Tampered'})
        self.business.refresh_from_db();self.assertEqual(self.business.name,'Business One')

    def test_stale_edits_and_deletion_do_not_overwrite(self):
        batch=self.batch();url=f"/api/inventory/{batch['id']}/"
        self.assertEqual(self.client.patch(url,{'quantity':'8','version':1}).status_code,200)
        self.assertEqual(self.client.patch(url,{'quantity':'2','version':1}).status_code,409)
        self.assertEqual(self.client.delete(url,{'version':1}).status_code,409)
        self.assertEqual(self.client.patch(url,{'quantity':'2'}).status_code,400)
        self.assertEqual(self.client.delete(url).status_code,400)
        self.assertEqual(self.client.get(url).data['quantity'],'8.000')

    def test_pos_token_adjustment_retries_are_idempotent(self):
        batch=self.batch();token=Token.objects.create(user=self.user)
        self.client.force_authenticate(None);self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        url=f"/api/inventory/{batch['id']}/adjust/"
        data={'delta':'-2.500','reason':'POS sale','reference':'sale-100'}
        first=self.client.post(url,data);second=self.client.post(url,data)
        self.assertEqual(first.status_code,201,first.data)
        self.assertEqual(second.status_code,200,second.data)
        self.assertTrue(second.data['replayed'])
        self.assertEqual(self.client.get(f"/api/inventory/{batch['id']}/").data['quantity'],'7.500')
        self.assertEqual(self.client.post(url,{**data,'delta':'-1'}).status_code,409)

    def test_adjustment_cannot_overdraw_or_exceed_precision(self):
        batch=self.batch();url=f"/api/inventory/{batch['id']}/adjust/"
        for delta in ['-11','0','0.0001','999999999.999']:
            self.assertEqual(self.client.post(url,{'delta':delta,'reason':'Test'}).status_code,400)
        self.assertEqual(StockTransaction.objects.count(),1)

    def test_csv_success_and_duplicate_replay_rollback(self):
        response=self.upload([self.csv_row(),self.csv_row(batch_number='CSV-2')])
        self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(response.data['imported'],2)
        self.assertEqual(self.upload([self.csv_row()]).status_code,400)
        self.assertEqual(InventoryBatch.objects.count(),2)
        self.assertEqual(StockTransaction.objects.filter(kind='imported').count(),2)

    def test_csv_bad_row_rolls_back_products_batches_alerts_and_audit(self):
        response=self.upload([self.csv_row(sku='NEW',barcode='NEW',product_name='New product'),self.csv_row(quantity='-1')])
        self.assertEqual(response.status_code,400,response.data)
        self.assertEqual(str(response.data['row']),'3')
        self.assertFalse(Product.objects.filter(sku='NEW').exists())
        self.assertEqual(InventoryBatch.objects.count(),0)
        self.assertEqual(StockTransaction.objects.count(),0)
        self.assertEqual(ExpiryAlert.objects.count(),0)

    def test_csv_malformed_headers_encoding_empty_and_limits(self):
        for contents in [b'sku,quantity\nTOM,1', b'', b'\xff\xfe', (','.join(HEADERS)+'\n').encode(), b'x'*(2*1024*1024+1)]:
            response=self.client.post('/api/inventory/import-csv/',{'file':SimpleUploadedFile('bad.csv',contents)},format='multipart')
            self.assertEqual(response.status_code,400,response.data)
        self.assertEqual(self.upload([self.csv_row()]*1001).status_code,400)

    def test_csv_rejects_conflicting_catalog_details_and_unknown_categories(self):
        for changes in [{'product_name':'Changed'},{'category':'invalid'},{'barcode':'DIFFERENT'}]:
            self.assertEqual(self.upload([self.csv_row(**changes)]).status_code,400)

    def test_csv_uses_current_business_catalog(self):
        self.client.force_authenticate(self.outsider)
        response=self.upload([self.csv_row(product_name='Private tomatoes')])
        self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(InventoryBatch.objects.get().business,self.other)
        self.assertEqual(InventoryBatch.objects.get().product,self.other_product)

    def test_donation_decrements_stock_and_keeps_log_after_deletion(self):
        batch=self.batch();url=f"/api/inventory/{batch['id']}/"
        response=self.client.post('/api/donations/',{'batch':batch['id'],'quantity':'3.500','recipient':'Local kitchen'})
        self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(self.client.get(url).data['quantity'],'6.500')
        self.assertEqual(StockTransaction.objects.first().kind,'donated')
        self.assertEqual(self.client.delete(url,{'version':2}).status_code,204)
        self.assertEqual(DonationLog.objects.get().snapshot['product'],'Tomatoes')

    def test_donation_rejects_expired_negative_and_excess_quantities(self):
        batch=self.batch()
        for quantity in ['0','-1','11']:
            self.assertEqual(self.client.post('/api/donations/',{'batch':batch['id'],'quantity':quantity,'recipient':'Kitchen'}).status_code,400)
        expired=self.batch(batch_number='EXPIRED',expiry_date=(self.today-timedelta(days=1)).isoformat())
        self.assertEqual(self.client.post('/api/donations/',{'batch':expired['id'],'quantity':'1','recipient':'Kitchen'}).status_code,400)
        self.assertEqual(DonationLog.objects.count(),0)

    def test_product_uniqueness_and_shared_taxonomy_read_only(self):
        payload={'name':'Duplicate','sku':'TOM-1','barcode':'NEW','unit':'kg','category':self.category.id}
        self.assertEqual(self.client.post('/api/products/',payload).status_code,400)
        self.assertEqual(self.client.post('/api/products/',{**payload,'sku':'NEW','barcode':'123456789'}).status_code,400)
        self.assertEqual(self.client.post('/api/categories/',{}).status_code,405)
        self.assertEqual(len(self.client.get('/api/categories/').data),10)

    def test_filters_and_barcode_search(self):
        self.batch()
        self.assertEqual(self.client.get('/api/inventory/?search=TOM-1').data['count'],1)
        self.assertEqual(self.client.get('/api/inventory/?barcode=123456789').data['count'],1)
        self.assertEqual(self.client.get('/api/products/?barcode=123456789').data['count'],1)
        self.assertEqual(self.client.get('/api/inventory/?category=dairy').data['count'],0)
        self.assertEqual(self.client.get('/api/inventory/?status=wrong').status_code,400)

    def test_management_command_and_celery_task(self):
        self.batch()
        output=io.StringIO();call_command('check_expiry',stdout=output)
        self.assertIn('1 active expiry alerts',output.getvalue())
        self.assertEqual(refresh_expiry_alerts.run(),{'active_alerts':1})

    def test_expiry_watcher_runs_and_stops_cleanly(self):
        self.batch()
        output=io.StringIO()
        with patch('inventory.management.commands.check_expiry.time.sleep', side_effect=KeyboardInterrupt):
            call_command('check_expiry',watch=True,interval=10,stdout=output)
        self.assertIn('1 active expiry alerts',output.getvalue())
        self.assertIn('Expiry watcher stopped',output.getvalue())

    def test_stale_stock_adjustment_rejects_lost_update(self):
        from inventory.services import adjust_batch, Conflict
        data=self.batch()
        first=InventoryBatch.objects.get(pk=data['id'])
        stale=InventoryBatch.objects.get(pk=data['id'])
        adjust_batch(first,Decimal('-3'),self.user,'First edit')
        with self.assertRaises(Conflict):
            adjust_batch(stale,Decimal('-4'),self.user,'Stale edit')
        first.refresh_from_db()
        self.assertEqual(first.quantity,Decimal('7'))

    def test_csv_template_matches_import_contract(self):
        response=self.client.get('/api/inventory/csv-template/')
        upload=SimpleUploadedFile('template.csv',response.content)
        imported=self.client.post('/api/inventory/import-csv/',{'file':upload},format='multipart')
        self.assertEqual(imported.status_code,201,imported.data)

    def test_session_auth_requires_csrf_for_mutations(self):
        client=APIClient(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post('/api/inventory/',self.payload()).status_code,403)
        self.assertEqual(client.get('/').status_code,200)
        token=client.cookies['csrftoken'].value
        self.assertEqual(client.post('/api/inventory/',self.payload(),HTTP_X_CSRFTOKEN=token).status_code,201)

    def test_login_dashboard_logout(self):
        client=APIClient()
        self.assertEqual(client.get('/').status_code,302)
        self.assertEqual(client.get('/login/').status_code,200)
        self.assertTrue(client.login(username='member',password='Testing-password-283!'))
        self.assertContains(client.get('/'),'FoodBridge')
        self.assertEqual(client.get('/logout/').status_code,405)
        self.assertEqual(client.post('/logout/').status_code,302)
