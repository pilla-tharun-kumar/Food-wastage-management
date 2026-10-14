import getpass
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from inventory.models import Business, Membership


class Command(BaseCommand):
    help = 'Create a business and its first user with a securely prompted password.'
    def add_arguments(self, parser):
        parser.add_argument('--name', required=True)
        parser.add_argument('--username', required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.filter(username=options['username']).exists():
            raise CommandError('Username already exists; no changes made.')
        password = getpass.getpass('Password: ')
        if password != getpass.getpass('Confirm password: '):
            raise CommandError('Passwords do not match.')
        user = User(username=options['username'])
        try:
            user.full_clean(exclude=['password'])
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError(str(exc))
        user.set_password(password)
        user.save()
        business = Business(name=options['name'])
        business.full_clean()
        business.save()
        Membership.objects.create(user=user, business=business)
        self.stdout.write(self.style.SUCCESS(f'Created {business.name}. Sign in as {user.username}.'))
