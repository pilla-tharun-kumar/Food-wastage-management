import time

from django.core.management.base import BaseCommand

from inventory.models import Business
from inventory.prediction import run_predictions


class Command(BaseCommand):
    help = 'Run daily demand forecasts, waste scores and reorder calculations.'

    def add_arguments(self, parser):
        parser.add_argument('--business-id', type=int)
        parser.add_argument('--model', choices=['auto', 'seasonal', 'prophet', 'lstm', 'knn'], default='seasonal')
        parser.add_argument('--watch', action='store_true')
        parser.add_argument('--interval', type=int, default=86400)

    def handle(self, *args, **options):
        business = Business.objects.get(pk=options['business_id']) if options['business_id'] else None
        if options['watch'] and options['interval'] < 60:
            raise ValueError('Watch interval must be at least 60 seconds.')
        while True:
            result = run_predictions(business, model=options['model'])
            self.stdout.write(f"Predictions updated: {len(result['updated'])}; skipped: {len(result['skipped'])}.")
            for item in result['skipped']:
                self.stdout.write(f"  Product {item['product_id']}: {item['reason']}")
            if not options['watch']:
                return
            time.sleep(options['interval'])
