from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.views import LoginView
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Business, DonationLog, InventoryBatch, NGOProfile, Product, SurplusOffer


def is_platform_admin(user):
    return user.is_authenticated and user.is_superuser


class SuperAdminLoginView(LoginView):
    template_name = 'superadmin_login.html'
    redirect_authenticated_user = False

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_superuser:
            return redirect('/superadmin/')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['account_access_error'] = bool(self.request.user.is_authenticated)
        return context

    def form_valid(self, form):
        if not form.get_user().is_superuser:
            form.add_error(None, 'This account is not a platform super admin.')
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self):
        return '/superadmin/'


admin_required = user_passes_test(is_platform_admin, login_url='/superadmin/login/')


@admin_required
def dashboard(request):
    businesses = Business.objects.annotate(members_count=Count('members'), products_count=Count('product', distinct=True), batches_count=Count('inventorybatch', distinct=True)).order_by('name')
    ngos = NGOProfile.objects.select_related('user').order_by('organization_name')
    offers = SurplusOffer.objects.select_related('business', 'batch__product', 'accepted_by').order_by('-created_at')[:30]
    return render(request, 'superadmin_dashboard.html', {
        'businesses': businesses, 'ngos': ngos, 'offers': offers,
        'stats': {'businesses': Business.objects.count(), 'ngos': NGOProfile.objects.count(),
                  'products': Product.objects.count(), 'batches': InventoryBatch.objects.count(),
                  'donations': DonationLog.objects.count(), 'open_offers': SurplusOffer.objects.filter(status__in=['open','requested','accepted','picked_up']).count()},
    })


@admin_required
@require_POST
def delete_business(request, pk):
    business = get_object_or_404(Business, pk=pk)
    business.delete()
    return redirect('/superadmin/#businesses')


@admin_required
@require_POST
def delete_ngo(request, pk):
    ngo = get_object_or_404(NGOProfile, pk=pk)
    ngo.user.delete()
    return redirect('/superadmin/#ngos')
