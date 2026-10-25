from celery import shared_task
from .services import refresh_alerts
from .prediction import run_predictions


@shared_task
def refresh_expiry_alerts():
    return {'active_alerts': refresh_alerts()}


@shared_task
def refresh_demand_predictions():
    result = run_predictions()
    return {'updated': len(result['updated']), 'skipped': len(result['skipped'])}
