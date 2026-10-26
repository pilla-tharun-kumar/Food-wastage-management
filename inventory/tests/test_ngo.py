from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from inventory.models import Business, Category, DonationLog, InventoryBatch, Membership, NGOProfile, Notification, Product, StockTransaction, SurplusOffer


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class NGOFlowTests(TestCase):
    def setUp(self):
        user = get_user_model()
        self.business_user = user.objects.create_user('seller', password='Strong-test-password-283!')
        self.business = Business.objects.create(name='Corner Kitchen')
        Membership.objects.create(user=self.business_user, business=self.business)
        self.ngo_user = user.objects.create_user('partner', password='Strong-test-password-283!')
        self.ngo = NGOProfile.objects.create(user=self.ngo_user, organization_name='Local Pantry', service_area='Chennai')
        self.other_ngo = NGOProfile.objects.create(
            user=user.objects.create_user('otherpartner', password='Strong-test-password-283!'),
            organization_name='Other Pantry', service_area='Chennai')
        category = Category.objects.get(code='vegetables')
        product = Product.objects.create(business=self.business, name='Tomatoes', sku='TOM-101', category=category, unit='kg')
        self.batch = InventoryBatch.objects.create(business=self.business, product=product, batch_number='A',
            quantity=Decimal('10'), received_date=timezone.localdate(), expiry_date=timezone.localdate() + timedelta(days=3))

    def test_landing_and_role_specific_signup_and_login(self):
        self.assertContains(self.client.get('/'), 'Good food should go')
        self.assertEqual(self.client.get('/login/ngo/').status_code, 200)
        self.assertContains(self.client.get('/signup/ngo/'), 'Join as an NGO')
        self.assertEqual(self.client.post('/login/ngo/', {'username': 'seller', 'password': 'Strong-test-password-283!'}).status_code, 200)
        self.assertRedirects(self.client.post('/login/ngo/', {'username': 'partner', 'password': 'Strong-test-password-283!'}), '/ngo/')
        self.assertContains(self.client.get('/'), 'Good food should go')
        self.assertEqual(self.client.get('/api/inventory/').status_code, 403)
        self.assertRedirects(self.client.post('/logout/', {'next': '/login/ngo/'}), '/login/ngo/')

    def test_publish_request_accept_pickup_and_delivery(self):
        self.client.force_login(self.business_user)
        response = self.client.post('/surplus/', {'batch': self.batch.pk, 'quantity': '3.5', 'pickup_notes': 'Collect at front desk'})
        self.assertRedirects(response, '/surplus/')
        offer = SurplusOffer.objects.get()
        self.assertEqual(offer.status, 'open')
        self.assertEqual(Notification.objects.filter(kind='available').count(), 2)
        self.client.force_login(self.ngo_user)
        self.assertContains(self.client.get('/ngo/offers/'), 'Tomatoes')
        self.assertRedirects(self.client.post(f'/ngo/offers/{offer.pk}/request/'), '/ngo/requests/')
        offer.refresh_from_db(); self.batch.refresh_from_db()
        self.assertEqual(offer.status, 'requested')
        self.assertEqual(self.batch.quantity, Decimal('6.5'))
        self.assertEqual(DonationLog.objects.count(), 0)
        self.assertEqual(StockTransaction.objects.latest('id').kind, 'allocated')
        self.assertEqual(Notification.objects.filter(recipient=self.ngo_user, kind='expiry').count(), 1)
        self.client.post(f'/ngo/offers/{offer.pk}/request/')
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, Decimal('6.5'))
        self.assertEqual(Notification.objects.filter(recipient=self.business_user, kind='request').count(), 1)
        self.client.force_login(self.business_user)
        self.assertRedirects(self.client.post(f'/surplus/{offer.pk}/approve/'), '/surplus/')
        offer.refresh_from_db()
        self.assertEqual(offer.status, 'accepted')
        self.assertEqual(Notification.objects.filter(recipient=self.ngo_user, kind='accepted').count(), 1)
        self.client.force_login(self.other_ngo.user)
        self.assertEqual(self.client.post(f'/ngo/offers/{offer.pk}/pickup/').status_code, 404)
        self.client.force_login(self.ngo_user)
        self.assertRedirects(self.client.post(f'/ngo/offers/{offer.pk}/pickup/'), '/ngo/pickups/')
        self.assertEqual(DonationLog.objects.count(), 0)
        self.assertEqual(SurplusOffer.objects.get(pk=offer.pk).status, 'picked_up')
        self.assertRedirects(self.client.post(f'/ngo/offers/{offer.pk}/delivered/'), '/ngo/impact/')
        self.assertEqual(DonationLog.objects.count(), 1)
        self.assertEqual(DonationLog.objects.get().recipient, 'Local Pantry')
        self.assertEqual(SurplusOffer.objects.get(pk=offer.pk).status, 'delivered')
        self.client.post(f'/ngo/offers/{offer.pk}/delivered/')
        self.assertEqual(DonationLog.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(recipient=self.business_user, kind='delivered').count(), 1)
        self.assertEqual(self.client.get('/ngo/impact/').status_code, 200)

    def test_offer_quantity_and_role_boundaries(self):
        self.client.force_login(self.business_user)
        self.assertEqual(self.client.post('/surplus/', {'batch': self.batch.pk, 'quantity': '11'}).status_code, 200)
        self.assertEqual(SurplusOffer.objects.count(), 0)
        self.assertEqual(self.client.get('/ngo/').status_code, 403)
        self.client.force_login(self.ngo_user)
        self.assertEqual(self.client.get('/surplus/').status_code, 403)
        self.assertEqual(self.client.post('/surplus/', {'batch': self.batch.pk, 'quantity': '2'}).status_code, 403)

    def test_business_can_cancel_open_offer(self):
        offer = SurplusOffer.objects.create(business=self.business, batch=self.batch, quantity=Decimal('2'))
        self.client.force_login(self.business_user)
        self.assertRedirects(self.client.post(f'/surplus/{offer.pk}/cancel/'), '/surplus/')
        offer.refresh_from_db()
        self.assertEqual(offer.status, 'cancelled')
        self.client.force_login(self.ngo_user)
        self.assertNotContains(self.client.get('/ngo/offers/'), 'Tomatoes')

    def test_ngo_signup_creates_separate_partner_account(self):
        self.client.logout()
        response = self.client.post('/signup/ngo/', {
            'username': 'newngo', 'email': 'ngo@example.org', 'organization_name': 'New Pantry',
            'service_area': 'Chennai', 'password1': 'Strong-test-password-283!',
            'password2': 'Strong-test-password-283!',
        })
        self.assertRedirects(response, '/ngo/')
        new_user = get_user_model().objects.get(username='newngo')
        self.assertEqual(new_user.ngo_profile.organization_name, 'New Pantry')
        self.assertFalse(hasattr(new_user, 'membership'))

    def test_public_navigation_and_both_notification_bells(self):
        for url in ('/', '/login/', '/login/ngo/', '/signup/', '/signup/ngo/'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'Business sign in')
            self.assertContains(response, 'NGO sign in')
        self.client.force_login(self.business_user)
        self.assertContains(self.client.get('/app/'), '/notifications/')
        self.assertContains(self.client.get('/notifications/'), 'Notifications')
        self.client.force_login(self.ngo_user)
        self.assertContains(self.client.get('/ngo/'), '/notifications/')

    def test_only_owning_business_can_approve_request(self):
        offer = SurplusOffer.objects.create(business=self.business, batch=self.batch, quantity=Decimal('2'))
        self.client.force_login(self.ngo_user)
        self.client.post(f'/ngo/offers/{offer.pk}/request/')
        self.assertEqual(self.client.post(f'/surplus/{offer.pk}/approve/').status_code, 403)
        offer.refresh_from_db()
        self.assertEqual(offer.status, 'requested')
        self.client.force_login(self.business_user)
        self.client.post(f'/surplus/{offer.pk}/approve/')
        offer.refresh_from_db()
        self.assertEqual(offer.status, 'accepted')

    def test_declining_request_releases_full_reservation(self):
        offer = SurplusOffer.objects.create(business=self.business, batch=self.batch, quantity=Decimal('10'))
        self.client.force_login(self.ngo_user)
        self.client.post(f'/ngo/offers/{offer.pk}/request/')
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, 0)
        self.assertEqual(Notification.objects.filter(recipient=self.ngo_user, kind='expiry').count(), 1)
        self.client.force_login(self.business_user)
        self.client.post(f'/surplus/{offer.pk}/cancel/')
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity, 10)
        self.assertEqual(SurplusOffer.objects.get(pk=offer.pk).status, 'cancelled')
        self.assertEqual(Notification.objects.filter(recipient=self.ngo_user, kind='cancelled').count(), 1)

    def test_csrf_required_for_request(self):
        offer = SurplusOffer.objects.create(business=self.business, batch=self.batch, quantity=Decimal('2'))
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.ngo_user)
        self.assertEqual(client.post(f'/ngo/offers/{offer.pk}/request/').status_code, 403)
        self.assertEqual(SurplusOffer.objects.get().status, 'open')

    def test_notifications_are_private_and_expiry_is_deduplicated(self):
        from inventory.services import refresh_alerts
        refresh_alerts(self.business)
        refresh_alerts(self.business)
        self.assertEqual(Notification.objects.filter(recipient=self.business_user, kind='expiry').count(), 1)
        self.client.force_login(self.ngo_user)
        self.assertNotContains(self.client.get('/notifications/'), 'Tomatoes')
        item = Notification.objects.get(recipient=self.business_user, kind='expiry')
        self.assertEqual(self.client.post(f'/notifications/{item.pk}/read/').status_code, 404)
        self.client.force_login(self.business_user)
        self.assertContains(self.client.get('/notifications/'), 'Tomatoes')
        self.assertRedirects(self.client.post(f'/notifications/{item.pk}/read/'), '/app/?section=alerts', fetch_redirect_response=False)
        item.refresh_from_db()
        self.assertIsNotNone(item.read_at)
