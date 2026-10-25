import csv
import io
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Max, Min, Q
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from .csv_import import HEADERS, import_inventory
from .models import (Category, CategoryPredictionSnapshot, DemandObservation, DonationLog, ExpiryAlert, InventoryBatch,
                     PredictionSnapshot, Product, StockTransaction)
from .prediction import (HEADERS as DEMAND_HEADERS, category_history, import_history,
                         predict_product, run_predictions)
from forecasting.core import ForecastError
from .serializers import (AdjustmentSerializer, AlertSerializer, BatchSerializer, BusinessSerializer,
                          CategoryPredictionSerializer, CategorySerializer, DemandObservationSerializer, DonationSerializer,
                          PredictionSnapshotSerializer, ProductPlanningSerializer, ProductSerializer,
                          TransactionSerializer)
from .services import adjust_batch, create_batch, delete_batch, donate, refresh_alerts, update_batch
from .forms import SignupForm
from .models import Business, Membership


def signup(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = SignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            business = Business.objects.create(name=form.cleaned_data['business_name'])
            Membership.objects.create(user=user, business=business)
        login(request, user)
        return redirect('dashboard')
    return render(request, 'signup.html', {'form': form})


@login_required
@ensure_csrf_cookie
def dashboard(request):
    if not hasattr(request.user, 'membership'):
        return render(request, 'no_business.html', status=403)
    return render(request, 'dashboard.html', {'business': request.user.membership.business})


class IntegrityResponseMixin:
    def handle_exception(self, exc):
        if isinstance(exc, IntegrityError):
            exc = ValidationError({'detail': 'This operation conflicts with an existing record. Refresh and check SKU, barcode, batch number or POS reference.'})
        return super().handle_exception(exc)

    @property
    def business(self):
        return self.request.user.membership.business


class ProductViewSet(IntegrityResponseMixin, mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = ProductSerializer
    def get_queryset(self):
        queryset = Product.objects.filter(business=self.business).select_related('category')
        if self.request.query_params.get('barcode'):
            queryset = queryset.filter(barcode=self.request.query_params['barcode'])
        if self.request.query_params.get('search'):
            term = self.request.query_params['search']
            queryset = queryset.filter(Q(name__icontains=term) | Q(sku__icontains=term))
        return queryset

    def perform_create(self, serializer):
        serializer.save(business=self.business)

    @action(detail=True, methods=['patch'])
    def planning(self, request, pk=None):
        product = self.get_object()
        serializer = ProductPlanningSerializer(product, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ProductSerializer(product, context={'request': request}).data)


class DemandViewSet(IntegrityResponseMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = DemandObservationSerializer

    def get_queryset(self):
        queryset = DemandObservation.objects.filter(business=self.business).select_related('product__category')
        product = self.request.query_params.get('product')
        if product:
            try:
                product_id = int(product)
                if product_id < 1:
                    raise ValueError
            except ValueError:
                raise ValidationError({'product': 'Use a positive product ID.'})
            queryset = queryset.filter(product_id=product_id)
        return queryset

    @action(detail=False, methods=['post'], url_path='import-csv')
    def import_csv(self, request):
        upload = request.FILES.get('file')
        if upload is None:
            raise ValidationError({'file': 'Attach a CSV using multipart form field "file".'})
        replace = request.query_params.get('replace', 'false').lower()
        if replace not in ('true', 'false'):
            raise ValidationError({'replace': 'Use true or false.'})
        return Response(import_history(upload, self.business, replace == 'true'), status=201)

    @action(detail=False, methods=['get'], url_path='csv-template')
    def csv_template(self, request):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="demand-history-template.csv"'
        writer = csv.writer(response)
        writer.writerow(DEMAND_HEADERS)
        writer.writerow([(timezone.localdate() - timedelta(days=1)).isoformat(), 'YOUR-SKU', '2.000', '3.000', '0.000'])
        return response

    @action(detail=False, methods=['get'], url_path='category-series')
    def category_series(self, request):
        category = Category.objects.filter(code=request.query_params.get('category')).first()
        unit = request.query_params.get('unit')
        if category is None or unit not in dict(Product._meta.get_field('unit').choices):
            raise ValidationError({'detail': 'Choose a valid category code and stock unit.'})
        data = category_history(self.business, category, unit, timezone.localdate() - timedelta(days=1))
        return Response({'category': category.code, 'unit': unit, 'complete_days': len(data), 'daily': data})

    @action(detail=False, methods=['get'])
    def coverage(self, request):
        records = DemandObservation.objects.filter(business=self.business)
        return Response({
            'records': records.count(),
            'sources': list(records.values('source').annotate(count=Count('id')).order_by('source')),
            'products': list(records.values('product_id', 'product__name', 'product__category__name', 'product__unit')
                             .annotate(days=Count('id'), first=Min('date'), last=Max('date')).order_by('product__name')),
        })


class PredictionViewSet(IntegrityResponseMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = PredictionSnapshotSerializer
    pagination_class = None

    def get_queryset(self):
        queryset = PredictionSnapshot.objects.filter(business=self.business).select_related('product__category')
        if self.action == 'list':
            queryset = queryset.filter(as_of_date=timezone.localdate() - timedelta(days=1))
        return queryset

    @action(detail=False, methods=['post'])
    def run(self, request):
        model = request.data.get('model', 'seasonal')
        if model not in ('auto', 'seasonal', 'prophet', 'lstm', 'knn'):
            raise ValidationError({'model': 'Use auto, seasonal, prophet, lstm or knn.'})
        product_id = request.data.get('product')
        if product_id:
            try:
                product_id = int(product_id)
                if product_id < 1:
                    raise ValueError
            except (TypeError, ValueError):
                raise ValidationError({'product': 'Use a positive product ID.'})
            product = Product.objects.filter(business=self.business, pk=product_id).select_related('business').first()
            if product is None:
                raise ValidationError({'product': 'Choose a product belonging to your business.'})
            try:
                snapshot = predict_product(product, model=model)
            except ForecastError as exc:
                raise ValidationError({'product': str(exc)}) from exc
            return Response(self.get_serializer(snapshot).data)
        return Response(run_predictions(self.business, model=model))

    @action(detail=False, methods=['get'])
    def categories(self, request):
        queryset = CategoryPredictionSnapshot.objects.filter(
            business=self.business, as_of_date=timezone.localdate() - timedelta(days=1)).select_related('category')
        return Response(CategoryPredictionSerializer(queryset, many=True).data)


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    pagination_class = None


class InventoryViewSet(IntegrityResponseMixin, viewsets.ModelViewSet):
    serializer_class = BatchSerializer

    def get_queryset(self):
        qs = InventoryBatch.objects.filter(business=self.business).select_related('business', 'product__category')
        params = self.request.query_params
        if params.get('search'):
            term = params['search']
            qs = qs.filter(Q(product__name__icontains=term) | Q(product__sku__icontains=term) | Q(batch_number__icontains=term))
        if params.get('barcode'):
            qs = qs.filter(product__barcode=params['barcode'])
        if params.get('category'):
            qs = qs.filter(product__category__code=params['category'])
        selected = params.get('status')
        if selected:
            if selected not in ['fresh', 'expiring', 'expired', 'out_of_stock']:
                raise ValidationError({'status': 'Use fresh, expiring, expired or out_of_stock.'})
            # Apply per-batch override thresholds consistently on SQLite and PostgreSQL.
            qs = qs.filter(pk__in=[batch.pk for batch in qs if batch.status == selected])
        return qs

    def perform_create(self, serializer):
        serializer.instance = create_batch(serializer.validated_data, self.business, self.request.user)

    def perform_update(self, serializer):
        serializer.instance = update_batch(serializer.instance, serializer.validated_data, self.request.user)

    def destroy(self, request, *args, **kwargs):
        batch = self.get_object()
        try:
            version = int(request.data.get('version', ''))
        except (ValueError, TypeError):
            raise ValidationError({'version': 'Include the current batch version in the DELETE JSON body.'})
        delete_batch(batch, request.user, version)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get'])
    def expiring(self, request):
        qs = self.get_queryset().filter(quantity__gt=0, expiry_date__gte=timezone.localdate())
        days = request.query_params.get('days')
        if days is not None:
            try:
                days = int(days)
                if not 0 <= days <= 365:
                    raise ValueError
            except ValueError:
                raise ValidationError({'days': 'Enter an integer between 0 and 365.'})
            qs = qs.filter(expiry_date__lte=timezone.localdate() + timedelta(days=days))
        else:
            qs = qs.filter(pk__in=[b.pk for b in qs if b.status == 'expiring'])
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(self.get_serializer(page, many=True).data)

    @action(detail=True, methods=['post'])
    def adjust(self, request, pk=None):
        batch = self.get_object()
        data = AdjustmentSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        event, created = adjust_batch(batch, values['delta'], request.user, values['reason'], values['reference'])
        return Response({'transaction': TransactionSerializer(event).data, 'replayed': not created}, status=201 if created else 200)

    @action(detail=False, methods=['post'], url_path='import-csv')
    def import_csv(self, request):
        upload = request.FILES.get('file')
        if upload is None:
            raise ValidationError({'file': 'Attach a CSV using multipart form field "file".'})
        ids = import_inventory(upload, request)
        return Response({'imported': len(ids), 'batch_ids': ids}, status=201)

    @action(detail=False, methods=['get'], url_path='csv-template')
    def csv_template(self, request):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="inventory-template.csv"'
        writer = csv.writer(response)
        writer.writerow(HEADERS)
        today = timezone.localdate()
        writer.writerow(['Fresh tomatoes', 'TOM-001', '8901234567890', 'vegetables', 'kg', 'TOM-001-A', '12.500',
                         today.isoformat(), (today + timedelta(days=5)).isoformat(), 'Produce shelf', '3', 'Sample row; edit before importing'])
        return response


class TransactionViewSet(IntegrityResponseMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = TransactionSerializer
    def get_queryset(self):
        return StockTransaction.objects.filter(business=self.business).select_related('actor')


class AlertViewSet(IntegrityResponseMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = AlertSerializer
    def get_queryset(self):
        refresh_alerts(self.business)
        return ExpiryAlert.objects.filter(business=self.business, resolved_at__isnull=True).select_related('batch__product')

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        alert = self.get_object()
        alert.read_at = timezone.now()
        alert.save(update_fields=['read_at'])
        return Response(self.get_serializer(alert).data)


class DonationViewSet(IntegrityResponseMixin, mixins.CreateModelMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = DonationSerializer
    def get_queryset(self):
        return DonationLog.objects.filter(business=self.business)

    def perform_create(self, serializer):
        values = serializer.validated_data
        serializer.instance = donate(values['batch'], values['quantity'], values['recipient'], values.get('notes', ''), self.request.user)


@api_view(['GET', 'PATCH'])
def business_settings(request):
    business = request.user.membership.business
    if request.method == 'PATCH':
        data = BusinessSerializer(business, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        data.save()
        refresh_alerts(business)
    return Response(BusinessSerializer(business).data)


@api_view(['GET'])
def summary(request):
    business = request.user.membership.business
    refresh_alerts(business)
    batches = list(InventoryBatch.objects.filter(business=business).select_related('business', 'product__category'))
    counts = {key: 0 for key in ['fresh', 'expiring', 'expired', 'out_of_stock']}
    for batch in batches:
        counts[batch.status] += 1
    return Response({'business': BusinessSerializer(business).data, 'today': timezone.localdate(),
                     'total_batches': len(batches), 'products': Product.objects.filter(business=business).count(),
                     'counts': counts, 'unread_alerts': ExpiryAlert.objects.filter(business=business, resolved_at__isnull=True, read_at__isnull=True).count(),
                     'donations': DonationLog.objects.filter(business=business).count(),
                     'categories': list(Product.objects.filter(business=business).values('category__name').annotate(products=Count('id')).order_by('category__name'))})
