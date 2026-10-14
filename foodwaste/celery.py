import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'foodwaste.settings')
app = Celery('foodwaste')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
