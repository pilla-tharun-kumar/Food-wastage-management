"""Persist in-app events for each account, with stable keys for repeatable jobs."""

from .models import Membership, NGOProfile, Notification


def notify(users, *, kind, key, title, message, target_url):
    for user_id in set(users):
        Notification.objects.get_or_create(
            recipient_id=user_id, dedupe_key=key,
            defaults={'kind': kind, 'title': title, 'message': message, 'target_url': target_url},
        )


def business_users(business):
    return Membership.objects.filter(business=business).values_list('user_id', flat=True)


def ngo_users():
    return NGOProfile.objects.values_list('user_id', flat=True)


def offer_notice(offer, kind):
    product = offer.batch.product.name
    quantity = f'{offer.quantity:g} {offer.batch.product.unit}'
    business = offer.business.name
    ngo_profile = offer.accepted_by if offer.accepted_by_id else None
    ngo = ngo_profile.organization_name if ngo_profile else 'An NGO'
    ngo_id = ngo_profile.user_id if ngo_profile else None
    details = {
        'available': (ngo_users(), 'Food available', f'{business} offered {quantity} of {product}.', '/ngo/offers/'),
        'request': (business_users(offer.business), 'Donation request', f'{ngo} requested {quantity} of {product}. Review and accept the request.', '/surplus/'),
        'accepted': ([ngo_id], 'Request accepted', f'{business} accepted your request for {quantity} of {product}. Plan your pickup.', '/ngo/pickups/'),
        'pickup': (list(business_users(offer.business)) + [ngo_id], 'Food picked up', f'{ngo} picked up {quantity} of {product}. Delivery confirmation is pending.', '/surplus/'),
        'delivered': (list(business_users(offer.business)) + [ngo_id], 'Food delivered', f'{quantity} of {product} was delivered to {ngo}.', '/surplus/'),
        'cancelled': ([ngo_id] if ngo_id else [], 'Request cancelled', f'{business} cancelled the {product} offer.', '/ngo/requests/'),
    }
    users, title, message, target = details[kind]
    if kind in ('pickup', 'delivered'):
        notify(business_users(offer.business), kind=kind, key=f'offer:{offer.pk}:{kind}', title=title,
               message=message, target_url='/surplus/')
        notify([ngo_id], kind=kind, key=f'offer:{offer.pk}:{kind}', title=title,
               message=message, target_url='/ngo/requests/')
    else:
        notify(users, kind=kind, key=f'offer:{offer.pk}:{kind}', title=title, message=message, target_url=target)
