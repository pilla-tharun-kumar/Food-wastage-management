from rest_framework import serializers
from .models import Business, Category, DonationLog, ExpiryAlert, InventoryBatch, Product, StockTransaction


class BusinessSerializer(serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = ['id', 'name', 'expiry_alert_days']
        read_only_fields = ['id', 'name']


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'code', 'name', 'perishability', 'storage', 'guidance']


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    storage = serializers.CharField(source='category.storage', read_only=True)
    perishability = serializers.CharField(source='category.perishability', read_only=True)

    class Meta:
        model = Product
        fields = ['id', 'name', 'sku', 'barcode', 'category', 'category_name', 'unit', 'storage', 'perishability']
        validators = []

    def validate(self, attrs):
        business = self.context['request'].user.membership.business
        for field in ['sku', 'barcode']:
            if attrs.get(field) and Product.objects.filter(business=business, **{field: attrs[field]}).exists():
                raise serializers.ValidationError({field: f'A product with this {field} already exists.'})
        return attrs


class BatchSerializer(serializers.ModelSerializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.none())
    product_name = serializers.CharField(source='product.name', read_only=True)
    sku = serializers.CharField(source='product.sku', read_only=True)
    barcode = serializers.CharField(source='product.barcode', read_only=True)
    unit = serializers.CharField(source='product.unit', read_only=True)
    category_name = serializers.CharField(source='product.category.name', read_only=True)
    category_id = serializers.IntegerField(source='product.category_id', read_only=True)
    storage = serializers.CharField(source='product.category.storage', read_only=True)
    perishability = serializers.CharField(source='product.category.perishability', read_only=True)
    days_to_expiry = serializers.IntegerField(read_only=True)
    status = serializers.CharField(read_only=True)
    effective_alert_days = serializers.IntegerField(read_only=True)
    version = serializers.IntegerField(min_value=1, required=False)

    class Meta:
        model = InventoryBatch
        fields = ['id', 'product', 'product_name', 'sku', 'barcode', 'unit', 'category_name', 'category_id',
                  'storage', 'perishability', 'batch_number', 'quantity', 'received_date', 'expiry_date',
                  'storage_location', 'alert_days', 'effective_alert_days', 'notes', 'days_to_expiry',
                  'status', 'version', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']
        validators = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request and hasattr(request.user, 'membership'):
            self.fields['product'].queryset = Product.objects.filter(business=request.user.membership.business)

    def validate(self, attrs):
        instance = self.instance
        if instance:
            if 'version' not in attrs:
                raise serializers.ValidationError({'version': 'Include the version returned when you loaded this batch.'})
            if 'product' in attrs and attrs['product'].id != instance.product_id:
                raise serializers.ValidationError({'product': 'A batch cannot be reassigned to a different product.'})
        else:
            attrs.pop('version', None)
        received = attrs.get('received_date', instance.received_date if instance else None)
        if received is None:
            from django.utils import timezone
            received = timezone.localdate()
        expiry = attrs.get('expiry_date', instance.expiry_date if instance else None)
        if expiry and expiry < received:
            raise serializers.ValidationError({'expiry_date': 'Expiry must be on or after the received date.'})
        product = attrs.get('product', instance.product if instance else None)
        batch_number = attrs.get('batch_number', instance.batch_number if instance else None)
        qs = InventoryBatch.objects.filter(business=self.context['request'].user.membership.business, product=product, batch_number=batch_number)
        if instance:
            qs = qs.exclude(pk=instance.pk)
        if qs.exists():
            raise serializers.ValidationError({'batch_number': 'This product already has a batch with this number.'})
        return attrs


class AdjustmentSerializer(serializers.Serializer):
    delta = serializers.DecimalField(max_digits=12, decimal_places=3)
    reason = serializers.CharField(max_length=250)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')

    def validate_delta(self, value):
        if value == 0:
            raise serializers.ValidationError('Enter a nonzero quantity change.')
        return value


class TransactionSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source='actor.username', read_only=True, default='Removed user')
    class Meta:
        model = StockTransaction
        fields = ['id', 'batch', 'actor_name', 'kind', 'delta', 'quantity_after', 'snapshot', 'note', 'reference', 'created_at']


class AlertSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='batch.product.name', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)
    quantity = serializers.DecimalField(source='batch.quantity', max_digits=12, decimal_places=3, read_only=True)
    unit = serializers.CharField(source='batch.product.unit', read_only=True)
    days_to_expiry = serializers.IntegerField(source='batch.days_to_expiry', read_only=True)
    class Meta:
        model = ExpiryAlert
        fields = ['id', 'batch', 'product_name', 'batch_number', 'quantity', 'unit', 'severity', 'expiry_date', 'days_to_expiry', 'read_at', 'created_at']


class DonationSerializer(serializers.ModelSerializer):
    batch = serializers.PrimaryKeyRelatedField(queryset=InventoryBatch.objects.none())
    class Meta:
        model = DonationLog
        fields = ['id', 'batch', 'recipient', 'quantity', 'notes', 'snapshot', 'created_at']
        read_only_fields = ['snapshot', 'created_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.context.get('request'):
            self.fields['batch'].queryset = InventoryBatch.objects.filter(
                business=self.context['request'].user.membership.business).select_related('product', 'business')

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError('Donation quantity must be positive.')
        return value
