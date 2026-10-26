"""Public entry and role-scoped surplus exchange pages."""

from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.db.models import F, Sum
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import NGOSignupForm
from .models import DonationLog, InventoryBatch, NGOProfile, Notification, SurplusOffer
from .notifications import offer_notice
from .services import adjust_batch, snapshot, sync_batch_alert


class RoleLoginView(LoginView):
    template_name = 'role_login.html'
    role = 'business'

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs) | {'role': self.role}

    def form_valid(self, form):
        user = form.get_user()
        if not hasattr(user, 'ngo_profile' if self.role == 'ngo' else 'membership'):
            form.add_error(None, 'This account belongs to the other workspace. Choose its sign-in page.')
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_default_redirect_url(self):
        return reverse('ngo_dashboard' if self.role == 'ngo' else 'dashboard')


def ngo_signup(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = NGOSignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            NGOProfile.objects.create(user=user, organization_name=form.cleaned_data['organization_name'].strip(),
                                      service_area=form.cleaned_data['service_area'].strip())
        login(request, user)
        return redirect('ngo_dashboard')
    return render(request, 'ngo_signup.html', {'form': form})


def _ngo_or_forbidden(request):
    return getattr(request.user, 'ngo_profile', None)


@login_required(login_url='/login/ngo/')
def ngo_dashboard(request, section='overview'):
    ngo = _ngo_or_forbidden(request)
    if ngo is None:
        return HttpResponseForbidden('NGO account required.')
    if section not in ('overview', 'offers', 'requests', 'pickups', 'impact'):
        section = 'overview'
    available = SurplusOffer.objects.filter(status='open', quantity__lte=F('batch__quantity'),
                                             batch__expiry_date__gte=timezone.localdate()).select_related(
                                                 'business', 'batch__product__category').order_by('batch__expiry_date', '-created_at')
    mine = SurplusOffer.objects.filter(accepted_by=ngo).select_related('business', 'batch__product').order_by('-created_at')
    completed = mine.filter(status='delivered')
    return render(request, 'ngo_dashboard.html', {
        'ngo': ngo, 'section': section, 'available': available[:30], 'mine': mine[:30],
        'pickups': mine.filter(status__in=['accepted', 'picked_up'])[:30], 'completed': completed[:30],
        'pending_count': mine.filter(status__in=['accepted', 'picked_up']).count(), 'completed_count': completed.count(),
        'open_count': available.count(), 'partner_count': available.values('business_id').distinct().count(),
        'completed_partner_count': completed.values('business_id').distinct().count(),
        'recent_offers': available[:4], 'recent_requests': mine[:4],
    })


class OfferForm(forms.ModelForm):
    class Meta:
        model = SurplusOffer
        fields = ('batch', 'quantity', 'pickup_notes')
        widgets = {'pickup_notes': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        self.fields['batch'].queryset = InventoryBatch.objects.filter(
            business=business, quantity__gt=0, expiry_date__gte=timezone.localdate()).select_related('product')
        self.fields['batch'].label_from_instance = lambda batch: (
            f'{batch.product.name} · {batch.batch_number} · {batch.quantity} {batch.product.unit} available')

    def clean(self):
        data = super().clean()
        batch, quantity = data.get('batch'), data.get('quantity')
        if batch and quantity:
            reserved = SurplusOffer.objects.filter(batch=batch, status='open').aggregate(total=Sum('quantity'))['total'] or Decimal('0')
            if quantity + reserved > batch.quantity:
                self.add_error('quantity', f'Only {batch.quantity - reserved} {batch.product.unit} remains available.')
        return data


@login_required
def business_surplus(request):
    if not hasattr(request.user, 'membership'):
        return HttpResponseForbidden('Business account required.')
    business = request.user.membership.business
    form = OfferForm(request.POST or None, business=business)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            batch = InventoryBatch.objects.select_for_update().get(pk=form.cleaned_data['batch'].pk, business=business)
            reserved = SurplusOffer.objects.filter(batch=batch, status='open').aggregate(total=Sum('quantity'))['total'] or Decimal('0')
            if form.cleaned_data['quantity'] + reserved > batch.quantity or batch.days_to_expiry < 0:
                form.add_error('quantity', 'Stock changed. Review the available quantity and try again.')
            else:
                offer = form.save(commit=False)
                offer.business = business
                offer.batch = batch
                offer.save()
                offer_notice(offer, 'available')
                messages.success(request, 'Surplus offer is live for NGO partners.')
                return redirect('business_surplus')
    offers = SurplusOffer.objects.filter(business=business).select_related('batch__product', 'accepted_by')[:50]
    return render(request, 'business_surplus.html', {'business': business, 'offers': offers, 'form': form})


@login_required
@require_POST
@transaction.atomic
def cancel_offer(request, pk):
    if not hasattr(request.user, 'membership'):
        return HttpResponseForbidden('Business account required.')
    offer = get_object_or_404(SurplusOffer.objects.select_for_update(),
                              pk=pk, business=request.user.membership.business)
    if offer.status in ('open', 'requested', 'accepted'):
        if offer.status in ('requested', 'accepted'):
            batch = InventoryBatch.objects.select_for_update().get(pk=offer.batch_id)
            adjust_batch(batch, offer.quantity, request.user, note='NGO request declined; stock released', kind='adjusted')
        offer.status = 'cancelled'
        offer.save(update_fields=['status'])
        offer_notice(offer, 'cancelled')
        messages.success(request, 'Offer cancelled and any reserved stock released.')
    else:
        messages.error(request, 'Picked up or delivered offers cannot be cancelled here.')
    return redirect('business_surplus')


@login_required(login_url='/login/ngo/')
@require_POST
@transaction.atomic
def request_offer(request, pk):
    ngo = _ngo_or_forbidden(request)
    if ngo is None:
        return HttpResponseForbidden('NGO account required.')
    offer = get_object_or_404(SurplusOffer.objects.select_for_update(), pk=pk)
    batch = InventoryBatch.objects.select_for_update().get(pk=offer.batch_id)
    if offer.status != 'open' or batch.days_to_expiry < 0 or batch.quantity < offer.quantity:
        messages.error(request, 'This offer is no longer available.')
        return redirect('ngo_offers')
    adjust_batch(batch, -offer.quantity, request.user, note=f'Allocated to {ngo.organization_name}', kind='allocated')
    offer.status = 'requested'
    offer.accepted_by = ngo
    offer.requested_at = timezone.now()
    offer.save(update_fields=['status', 'accepted_by', 'requested_at'])
    offer_notice(offer, 'request')
    sync_batch_alert(batch)
    messages.success(request, 'Request sent. The food is reserved while the business reviews it.')
    return redirect('ngo_requests')


@login_required
@require_POST
@transaction.atomic
def approve_request(request, pk):
    if not hasattr(request.user, 'membership'):
        return HttpResponseForbidden('Business account required.')
    offer = get_object_or_404(SurplusOffer.objects.select_for_update().select_related('accepted_by__user', 'batch__product'),
                              pk=pk, business=request.user.membership.business)
    if offer.status != 'requested':
        messages.error(request, 'This request is no longer awaiting approval.')
    elif offer.batch.days_to_expiry < 0:
        messages.error(request, 'This food has expired. Decline the request and review the batch.')
    else:
        offer.status = 'accepted'
        offer.accepted_at = timezone.now()
        offer.save(update_fields=['status', 'accepted_at'])
        offer_notice(offer, 'accepted')
        messages.success(request, 'Request accepted. The NGO can now pick up the food.')
    return redirect('business_surplus')


@login_required(login_url='/login/ngo/')
@require_POST
@transaction.atomic
def confirm_pickup(request, pk):
    ngo = _ngo_or_forbidden(request)
    if ngo is None:
        return HttpResponseForbidden('NGO account required.')
    offer = get_object_or_404(SurplusOffer.objects.select_for_update().select_related('batch'), pk=pk, accepted_by=ngo)
    if offer.status != 'accepted':
        messages.error(request, 'This pickup is already complete or no longer available.')
        return redirect('ngo_pickups')
    if offer.batch.days_to_expiry < 0:
        messages.error(request, 'This food has expired and cannot be picked up. Contact the business to cancel the offer.')
        return redirect('ngo_pickups')
    offer.status = 'picked_up'
    offer.picked_up_at = timezone.now()
    offer.save(update_fields=['status', 'picked_up_at'])
    offer_notice(offer, 'pickup')
    messages.success(request, 'Pickup recorded. Confirm delivery when the food reaches your organization.')
    return redirect('ngo_pickups')


@login_required(login_url='/login/ngo/')
@require_POST
@transaction.atomic
def confirm_delivery(request, pk):
    ngo = _ngo_or_forbidden(request)
    if ngo is None:
        return HttpResponseForbidden('NGO account required.')
    offer = get_object_or_404(SurplusOffer.objects.select_for_update().select_related('batch__product', 'business'),
                              pk=pk, accepted_by=ngo)
    if offer.status != 'picked_up':
        messages.error(request, 'Record pickup before confirming delivery.')
        return redirect('ngo_pickups')
    DonationLog.objects.create(business=offer.business, batch=offer.batch, actor=request.user,
                               recipient=ngo.organization_name, quantity=offer.quantity,
                               notes=f'Delivery confirmed. {offer.pickup_notes}'.strip(), snapshot=snapshot(offer.batch))
    offer.status = 'delivered'
    offer.delivered_at = timezone.now()
    offer.completed_at = offer.delivered_at
    offer.save(update_fields=['status', 'delivered_at', 'completed_at'])
    offer_notice(offer, 'delivered')
    messages.success(request, 'Delivery confirmed and added to your impact history.')
    return redirect('ngo_impact')


@login_required
def notifications_page(request):
    ngo = _ngo_or_forbidden(request)
    if ngo is None and not hasattr(request.user, 'membership'):
        return HttpResponseForbidden('Workspace account required.')
    only_unread = request.GET.get('filter') == 'unread'
    items = Notification.objects.filter(recipient=request.user)
    if only_unread:
        items = items.filter(read_at__isnull=True)
    return render(request, 'notifications.html', {
        'items': items[:100], 'only_unread': only_unread, 'ngo': ngo,
        'workspace_url': reverse('ngo_dashboard' if ngo else 'dashboard'),
    })


@login_required
@require_POST
def read_notification(request, pk):
    item = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if item.read_at is None:
        item.read_at = timezone.now()
        item.save(update_fields=['read_at'])
    return redirect(item.target_url)


@login_required
@require_POST
def read_all_notifications(request):
    Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return redirect('notifications')
