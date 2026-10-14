import csv
import io
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from .csv_import import HEADERS, import_inventory
from .models import Category, DonationLog, ExpiryAlert, InventoryBatch, Product, StockTransaction
from .serializers import (AdjustmentSerializer, AlertSerializer, BatchSerializer, BusinessSerializer,
                          CategorySerializer, DonationSerializer, ProductSerializer, TransactionSerializer)
from .services import adjust_batch, create_batch, delete_batch, donate, refresh_alerts, update_batch


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
