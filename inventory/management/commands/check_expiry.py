import time
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from inventory.services import refresh_alerts


class Command(BaseCommand):
    help = 'Refresh expiry alerts for every business (safe to run repeatedly).'
    def add_arguments(self, parser):
        parser.add_argument('--watch', action='store_true', help='Keep refreshing until interrupted.')
        parser.add_argument('--interval', type=int, default=60, help='Seconds between checks in watch mode (minimum 10).')

    def handle(self, *args, **options):
        if options['interval'] < 10:
            raise CommandError('Use an interval of at least 10 seconds.')
        try:
            while True:
                close_old_connections()
                count = refresh_alerts()
                self.stdout.write(self.style.SUCCESS(f'{count} active expiry alerts.'))
                if not options['watch']:
                    break
                time.sleep(options['interval'])
        except KeyboardInterrupt:
            self.stdout.write('Expiry watcher stopped.')
