import secrets
from datetime import timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from inventory.models import Business, Category, Membership, Product, InventoryBatch
from inventory.services import create_batch, donate


class Command(BaseCommand):
    help = 'Create a local demo business with sample inventory and a randomly generated login password.'

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.filter(username='demo').exists():
            self.stdout.write('Demo user already exists. Data and password were left unchanged. Use changepassword demo if needed.')
            return
        password = secrets.token_urlsafe(12)
        user = User.objects.create_user('demo', password=password)
        business = Business.objects.create(name='Green Table Kitchen')
        Membership.objects.create(user=user, business=business)
        today = timezone.localdate()
        rows = [
            ('Heirloom tomatoes', 'TOM-001', '8901000000011', 'vegetables', 'kg', '18.500', 2, 'Produce shelf A'),
            ('Fresh whole milk', 'MLK-001', '8901000000028', 'dairy', 'litre', '24', 1, 'Walk-in chiller'),
            ('Sourdough loaves', 'BRD-001', '8901000000035', 'bakery', 'unit', '12', 0, 'Bakery rack'),
            ('Baby spinach', 'SPN-001', '8901000000042', 'vegetables', 'kg', '6.250', -1, 'Walk-in chiller'),
            ('Basmati rice', 'RIC-001', '8901000000059', 'grains', 'kg', '80', 180, 'Dry store'),
            ('Red apples', 'APL-001', '8901000000066', 'fruit', 'kg', '32', 14, 'Produce shelf B'),
            ('Greek yogurt', 'YGT-001', '8901000000073', 'dairy', 'pack', '36', 5, 'Walk-in chiller'),
            ('Frozen green peas', 'PEA-001', '8901000000080', 'frozen', 'kg', '20', 90, 'Freezer 1'),
        ]
        for name, sku, barcode, code, unit, quantity, days, location in rows:
            product = Product.objects.create(business=business, name=name, sku=sku, barcode=barcode, category=Category.objects.get(code=code), unit=unit)
            batch = create_batch({'product': product, 'batch_number': f'{sku}-A', 'quantity': Decimal(quantity),
                                 'received_date': today - timedelta(days=5), 'expiry_date': today + timedelta(days=days),
                                 'storage_location': location}, business, user)
            if code == 'bakery':
                donate(batch, Decimal('2'), 'Community kitchen (demo)', 'Sample donation log', user)
        self.stdout.write(self.style.SUCCESS('Demo inventory created. These records are sample data.'))
        self.stdout.write(f'Username: demo\nPassword: {password}')
