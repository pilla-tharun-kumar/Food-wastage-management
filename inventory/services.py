from decimal import Decimal
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError
from .models import Business, DonationLog, ExpiryAlert, InventoryBatch, StockTransaction, SurplusOffer
from .notifications import business_users, notify


class Conflict(APIException):
    status_code = 409
    default_detail = 'This batch changed since it was loaded. Refresh and try again.'


def snapshot(batch):
    return {'product': batch.product.name, 'sku': batch.product.sku, 'unit': batch.product.unit,
            'batch_number': batch.batch_number, 'expiry_date': batch.expiry_date.isoformat(),
            'received_date': batch.received_date.isoformat(), 'storage_location': batch.storage_location,
            'alert_days': batch.alert_days, 'notes': batch.notes}


def record(batch, actor, kind, delta, note='', reference=''):
    return StockTransaction.objects.create(
        business=batch.business, batch=batch, actor=actor, kind=kind, delta=delta,
        quantity_after=batch.quantity, snapshot=snapshot(batch), note=note, reference=reference,
    )


def sync_batch_alert(batch):
    state = batch.status
    if batch.days_to_expiry <= batch.effective_alert_days:
        ngo_severity = 'expired' if batch.days_to_expiry < 0 else 'expiring'
        ngo_ids = SurplusOffer.objects.filter(batch=batch, status__in=['requested', 'accepted', 'picked_up'],
                                              accepted_by__isnull=False).values_list('accepted_by__user_id', flat=True)
        notify(ngo_ids, kind='expiry', key=f'expiry:{batch.pk}:{batch.expiry_date}:{ngo_severity}',
               title='Requested food has expired' if ngo_severity == 'expired' else 'Requested food nearing expiry',
               message=f'{batch.product.name} from {batch.business.name} expires {batch.expiry_date:%d %b %Y}. Coordinate pickup promptly.',
               target_url='/ngo/requests/')
    if state not in ('expiring', 'expired'):
        ExpiryAlert.objects.filter(batch=batch, resolved_at__isnull=True).update(resolved_at=timezone.now())
        return
    alert, created = ExpiryAlert.objects.get_or_create(
        batch=batch, defaults={'business': batch.business, 'severity': state, 'expiry_date': batch.expiry_date})
    changed = not created and (alert.severity != state or alert.expiry_date != batch.expiry_date or alert.resolved_at)
    if changed:
        alert.severity, alert.expiry_date = state, batch.expiry_date
        alert.read_at = alert.resolved_at = None
        alert.save()
    notify(business_users(batch.business), kind='expiry',
           key=f'expiry:{batch.pk}:{batch.expiry_date}:{state}',
           title='Expired food' if state == 'expired' else 'Food nearing expiry',
           message=f'{batch.product.name} · batch {batch.batch_number} · expires {batch.expiry_date:%d %b %Y}.',
           target_url='/app/?section=alerts')


def refresh_alerts(business=None):
    batches = InventoryBatch.objects.select_related('product', 'business')
    if business is not None:
        batches = batches.filter(business=business)
    for batch in batches.iterator():
        sync_batch_alert(batch)
    alerts = ExpiryAlert.objects.filter(resolved_at__isnull=True)
    return alerts.filter(business=business).count() if business else alerts.count()


@transaction.atomic
def create_batch(data, business, actor, kind='created'):
    if data['product'].business_id != business.id:
        raise ValidationError({'product': 'Select a product belonging to your business.'})
    batch = InventoryBatch.objects.create(business=business, **data)
    record(batch, actor, kind, batch.quantity)
    sync_batch_alert(batch)
    return batch


@transaction.atomic
def update_batch(batch, data, actor):
    expected = data.pop('version')
    if expected != batch.version:
        raise Conflict()
    before = batch.quantity
    values = {**data, 'version': F('version') + 1, 'updated_at': timezone.now()}
    if not InventoryBatch.objects.filter(pk=batch.pk, version=expected).update(**values):
        raise Conflict()
    batch.refresh_from_db()
    record(batch, actor, 'updated', batch.quantity - before)
    sync_batch_alert(batch)
    return batch


@transaction.atomic
def adjust_batch(batch, delta, actor, note='', reference='', kind='adjusted'):
    if reference:
        previous = StockTransaction.objects.filter(business=batch.business, reference=reference).first()
        if previous:
            if previous.batch_id != batch.id or previous.delta != delta or previous.note != note or previous.kind != kind:
                raise Conflict('This reference was already used for a different stock operation.')
            return previous, False
    after = batch.quantity + delta
    if after < 0 or after > Decimal('999999999.999'):
        raise ValidationError({'delta': 'Adjustment would put stock outside the allowed range.'})
    if not InventoryBatch.objects.filter(pk=batch.pk, version=batch.version).update(
        quantity=after, version=F('version') + 1, updated_at=timezone.now()):
        raise Conflict()
    batch.refresh_from_db()
    event = record(batch, actor, kind, delta, note, reference)
    sync_batch_alert(batch)
    return event, True


@transaction.atomic
def delete_batch(batch, actor, version):
    if version != batch.version:
        raise Conflict()
    if not InventoryBatch.objects.filter(pk=batch.pk, version=version).update(version=F('version') + 1):
        raise Conflict()
    before = batch.quantity
    batch.quantity = Decimal(0)
    record(batch, actor, 'deleted', -before, 'Batch removed from inventory')
    batch.delete()


@transaction.atomic
def donate(batch, quantity, recipient, notes, actor):
    if batch.days_to_expiry < 0:
        raise ValidationError({'batch': 'Expired stock cannot be logged as a donation.'})
    adjust_batch(batch, -quantity, actor, note=f'Donation to {recipient}', kind='donated')
    return DonationLog.objects.create(business=batch.business, batch=batch, actor=actor,
        recipient=recipient, quantity=quantity, notes=notes, snapshot=snapshot(batch))
