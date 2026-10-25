from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import ValidationError

from inventory.models import Business
from inventory.prediction import MAX_BYTES, import_history


class Command(BaseCommand):
    help = 'Validate and atomically import daily sales, purchases and waste from CSV.'

    def add_arguments(self, parser):
        parser.add_argument('path', type=Path)
        parser.add_argument('--business-id', type=int, required=True)
        parser.add_argument('--replace', action='store_true')

    def handle(self, *args, **options):
        try:
            business = Business.objects.get(pk=options['business_id'])
            path = options['path']
            if path.stat().st_size > MAX_BYTES:
                raise CommandError('CSV must be 2 MB or smaller.')
            upload = SimpleUploadedFile(path.name, path.read_bytes(), content_type='text/csv')
            result = import_history(upload, business, options['replace'])
        except (OSError, Business.DoesNotExist, ValidationError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Imported {result['imported']} rows; replaced {result['replaced']}.")
