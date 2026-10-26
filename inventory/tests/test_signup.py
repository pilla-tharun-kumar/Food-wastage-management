from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from inventory.models import Business, Membership


class SignupTests(TestCase):
    def payload(self):
        return {'username': 'newmember', 'email': 'member@example.com', 'business_name': 'New Kitchen',
                'password1': 'Strong-test-password-829!', 'password2': 'Strong-test-password-829!'}

    def test_signup_creates_private_workspace_and_signs_in(self):
        response = self.client.post('/signup/', self.payload())
        self.assertRedirects(response, '/app/')
        user = get_user_model().objects.get(username='newmember')
        self.assertTrue(user.check_password(self.payload()['password1']))
        self.assertEqual(user.membership.business.name, 'New Kitchen')
        self.assertEqual(self.client.get('/api/inventory/').json()['count'], 0)

    def test_invalid_password_and_duplicate_do_not_create_workspace(self):
        bad = dict(self.payload(), password2='mismatch')
        self.assertEqual(self.client.post('/signup/', bad).status_code, 200)
        self.assertEqual(Business.objects.count(), 0)
        self.client.post('/signup/', self.payload())
        self.client.logout()
        self.client.post('/signup/', self.payload())
        self.assertEqual(Membership.objects.count(), 1)
        self.assertEqual(Business.objects.count(), 1)

    def test_signup_requires_csrf(self):
        self.assertEqual(Client(enforce_csrf_checks=True).post('/signup/', self.payload()).status_code, 403)
