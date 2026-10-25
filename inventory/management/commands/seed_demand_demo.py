"""Add labeled, deterministic sample history to the existing demo business only."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from inventory.models import DemandObservation, Product


class Command(BaseCommand):
    help = 'Generate 63 days of clearly labeled synthetic demand for the demo account.'

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username='demo').first()
        if user is None or not hasattr(user, 'membership'):
            raise CommandError('Run seed_demo first.')
        business = user.membership.business
        yesterday = timezone.localdate() - timedelta(days=1)
        created = 0
        for product in Product.objects.filter(business=business).order_by('id'):
            for offset in range(62, -1, -1):
                day = yesterday - timedelta(days=offset)
                weekday_factor = 1.35 if day.weekday() in (4, 5) else 0.8 if day.weekday() == 0 else 1.0
                baseline = 1.2 + (product.pk % 5) * 0.45
                sale = Decimal(str(round(baseline * weekday_factor * (1 + ((offset * 7 + product.pk) % 5 - 2) * 0.06), 3)))
                _, added = DemandObservation.objects.get_or_create(
                    business=business, product=product, date=day,
                    defaults={'sales_quantity': sale,
                              'purchase_quantity': sale * (2 if day.weekday() in (0, 3) else 0),
                              'waste_quantity': Decimal('0.100') if day.weekday() == 6 else Decimal('0'),
                              'source': 'demo'})
                created += added
        self.stdout.write(self.style.SUCCESS(f'Added {created} synthetic demo observations. These are not real sales records.'))
