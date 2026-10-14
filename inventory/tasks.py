from celery import shared_task
from .services import refresh_alerts


@shared_task
def refresh_expiry_alerts():
    return {'active_alerts': refresh_alerts()}
