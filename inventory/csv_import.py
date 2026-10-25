import csv
import io
from django.db import transaction
from rest_framework.exceptions import ValidationError
from .models import Category, Product
from .serializers import BatchSerializer, ProductSerializer
from .services import create_batch

HEADERS = ['product_name', 'sku', 'barcode', 'category', 'unit', 'batch_number', 'quantity',
           'received_date', 'expiry_date', 'storage_location', 'alert_days', 'notes']
REQUIRED = {'product_name', 'sku', 'category', 'unit', 'batch_number', 'quantity', 'received_date', 'expiry_date'}


@transaction.atomic
def import_inventory(upload, request):
    if upload.size > 2 * 1024 * 1024:
        raise ValidationError({'file': 'CSV files must be 2 MB or smaller.'})
    try:
        contents = upload.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValidationError({'file': 'Use a UTF-8 encoded CSV file.'})
    reader = csv.DictReader(io.StringIO(contents), strict=True)
    try:
        headers = reader.fieldnames or []
        if {'date', 'sku', 'sales_quantity', 'purchase_quantity', 'waste_quantity'}.issubset(headers):
            raise ValidationError({'file': 'This is a demand-history CSV. Open Waste intelligence → Import demand CSV to upload it. Inventory import requires product and stock-batch details.'})
        if len(headers) != len(set(headers)) or not REQUIRED.issubset(headers) or set(headers) - set(HEADERS):
            raise ValidationError({'file': f'Use the template headers. Required: {", ".join(sorted(REQUIRED))}.'})
        rows = []
        for row in reader:
            if len(rows) >= 1000:
                raise ValidationError({'file': 'A single import may contain at most 1,000 rows.'})
            rows.append(row)
    except csv.Error as exc:
        raise ValidationError({'file': f'Malformed CSV: {exc}'})
    if not rows:
        raise ValidationError({'file': 'The CSV contains no inventory rows.'})
    business = request.user.membership.business
    categories = {c.code: c for c in Category.objects.all()}
    ids = []
    for row_number, row in enumerate(rows, start=2):
        try:
            if None in row or any(value is None for value in row.values()):
                raise ValidationError('The number of cells does not match the header.')
            row = {k: v.strip() for k, v in row.items()}
            category = categories.get(row['category'])
            if not category:
                raise ValidationError({'category': 'Use a taxonomy code from GET /api/categories/.'})
            product_data = {'name': row['product_name'], 'sku': row['sku'], 'barcode': row.get('barcode', ''),
                            'category': category.pk, 'unit': row['unit']}
            product = Product.objects.filter(business=business, sku=row['sku']).first()
            if product:
                if any([product.name != product_data['name'], product.barcode != product_data['barcode'],
                        product.category_id != category.pk, product.unit != product_data['unit']]):
                    raise ValidationError({'sku': 'Existing SKU has different product details. Use its current name, barcode, category and unit.'})
            else:
                serializer = ProductSerializer(data=product_data, context={'request': request})
                serializer.is_valid(raise_exception=True)
                product = serializer.save(business=business)
            data = {k: row[k] for k in ['batch_number', 'quantity', 'received_date', 'expiry_date']}
            data.update(product=product.pk, storage_location=row.get('storage_location', ''),
                        notes=row.get('notes', ''), alert_days=row.get('alert_days') or None)
            serializer = BatchSerializer(data=data, context={'request': request})
            serializer.is_valid(raise_exception=True)
            batch = create_batch(serializer.validated_data, business, request.user, 'imported')
            ids.append(batch.pk)
        except ValidationError as exc:
            raise ValidationError({'row': row_number, 'errors': exc.detail, 'detail': 'Import cancelled. No rows were saved.'})
    return ids
