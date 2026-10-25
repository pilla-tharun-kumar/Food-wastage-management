from decimal import Decimal
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Business(models.Model):
    name = models.CharField(max_length=160)
    expiry_alert_days = models.PositiveSmallIntegerField(default=7, validators=[MaxValueValidator(365)])
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='membership')
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name='members')


class Category(models.Model):
    """Shared, read-only food taxonomy. Inventory and product records remain tenant-owned."""
    name = models.CharField(max_length=80, unique=True)
    code = models.SlugField(unique=True)
    perishability = models.CharField(max_length=10, choices=[('high', 'High'), ('medium', 'Medium'), ('low', 'Low')])
    storage = models.CharField(max_length=120)
    guidance = models.CharField(max_length=250)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    name = models.CharField(max_length=160)
    sku = models.CharField(max_length=64)
    barcode = models.CharField(max_length=128, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    unit = models.CharField(max_length=12, choices=[('kg', 'kg'), ('g', 'g'), ('litre', 'litre'), ('unit', 'unit'), ('pack', 'pack')], default='kg')
    storage_capacity = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True,
                                           validators=[MinValueValidator(0)])
    reorder_lead_days = models.PositiveSmallIntegerField(default=3, validators=[MaxValueValidator(30)])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name', 'id']
        constraints = [
            models.UniqueConstraint(fields=['business', 'sku'], name='unique_business_sku'),
            models.UniqueConstraint(fields=['business', 'barcode'], condition=~models.Q(barcode=''), name='unique_business_barcode'),
        ]

    def __str__(self):
        return f'{self.name} ({self.sku})'


class InventoryBatch(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='batches')
    batch_number = models.CharField(max_length=64)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(0)])
    received_date = models.DateField(default=timezone.localdate)
    expiry_date = models.DateField()
    storage_location = models.CharField(max_length=120, blank=True)
    alert_days = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(365)])
    notes = models.CharField(max_length=500, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['expiry_date', 'id']
        constraints = [
            models.UniqueConstraint(fields=['business', 'product', 'batch_number'], name='unique_product_batch'),
            models.CheckConstraint(condition=models.Q(quantity__gte=0), name='nonnegative_inventory'),
            models.CheckConstraint(condition=models.Q(expiry_date__gte=models.F('received_date')), name='valid_inventory_dates'),
        ]
        indexes = [models.Index(fields=['business', 'expiry_date'])]

    @property
    def days_to_expiry(self):
        return (self.expiry_date - timezone.localdate()).days

    @property
    def effective_alert_days(self):
        return self.alert_days if self.alert_days is not None else self.business.expiry_alert_days

    @property
    def status(self):
        if self.quantity == 0:
            return 'out_of_stock'
        if self.days_to_expiry < 0:
            return 'expired'
        if self.days_to_expiry <= self.effective_alert_days:
            return 'expiring'
        return 'fresh'


class StockTransaction(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    batch = models.ForeignKey(InventoryBatch, on_delete=models.SET_NULL, null=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    kind = models.CharField(max_length=16, choices=[(s, s) for s in ['created', 'updated', 'adjusted', 'deleted', 'donated', 'imported']])
    delta = models.DecimalField(max_digits=12, decimal_places=3)
    quantity_after = models.DecimalField(max_digits=12, decimal_places=3)
    snapshot = models.JSONField()
    note = models.CharField(max_length=250, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [models.UniqueConstraint(fields=['business', 'reference'], condition=~models.Q(reference=''), name='unique_pos_reference')]


class ExpiryAlert(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    batch = models.OneToOneField(InventoryBatch, on_delete=models.CASCADE, related_name='alert')
    severity = models.CharField(max_length=12)
    expiry_date = models.DateField()
    read_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['expiry_date', 'id']


class DonationLog(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    batch = models.ForeignKey(InventoryBatch, on_delete=models.SET_NULL, null=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    recipient = models.CharField(max_length=160)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal('0.001'))])
    snapshot = models.JSONField()
    notes = models.CharField(max_length=250, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class DemandObservation(models.Model):
    """An explicit daily record; absent dates must never be interpreted as zero demand."""
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='demand_history')
    date = models.DateField()
    sales_quantity = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(0)])
    purchase_quantity = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(0)])
    waste_quantity = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(0)])
    source = models.CharField(max_length=12, choices=[('csv', 'CSV'), ('demo', 'Demo'), ('manual', 'Manual')], default='csv')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', 'product_id']
        constraints = [models.UniqueConstraint(fields=['business', 'product', 'date'], name='unique_daily_product_demand')]
        indexes = [models.Index(fields=['business', 'date'])]


class PredictionSnapshot(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='predictions')
    as_of_date = models.DateField()
    model_name = models.CharField(max_length=16)
    history_days = models.PositiveSmallIntegerField()
    backtest_mae = models.DecimalField(max_digits=12, decimal_places=3, null=True)
    daily_forecast = models.JSONField()
    forecast_7d = models.DecimalField(max_digits=12, decimal_places=3)
    stock_quantity = models.DecimalField(max_digits=12, decimal_places=3)
    nearest_expiry_date = models.DateField(null=True)
    risk_score = models.PositiveSmallIntegerField()
    risk_level = models.CharField(max_length=8)
    expected_surplus = models.DecimalField(max_digits=12, decimal_places=3)
    reorder_quantity = models.DecimalField(max_digits=12, decimal_places=3, null=True)
    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-as_of_date', '-risk_score', 'product_id']
        constraints = [models.UniqueConstraint(fields=['business', 'product', 'as_of_date'], name='unique_daily_product_prediction')]


class CategoryPredictionSnapshot(models.Model):
    """Category demand is separated by stock unit so unlike quantities are never added."""
    business = models.ForeignKey(Business, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    unit = models.CharField(max_length=12)
    as_of_date = models.DateField()
    model_name = models.CharField(max_length=16)
    history_days = models.PositiveSmallIntegerField()
    backtest_mae = models.DecimalField(max_digits=12, decimal_places=3, null=True)
    daily_forecast = models.JSONField()
    forecast_7d = models.DecimalField(max_digits=12, decimal_places=3)
    generated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category__name', 'unit']
        constraints = [models.UniqueConstraint(fields=['business', 'category', 'unit', 'as_of_date'],
                                               name='unique_daily_category_prediction')]
