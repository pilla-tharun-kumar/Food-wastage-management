from django.db import migrations

TAXONOMY = [
    ('vegetables', 'Vegetables', 'high', 'Chilled or cool dry storage, by product', 'Separate delicate greens from heavy produce. Follow the supplier label for storage conditions.'),
    ('fruit', 'Fruit', 'medium', 'Cool, ventilated storage; chill as labelled', 'Separate ripe fruit from sensitive produce and check for bruising.'),
    ('dairy', 'Dairy & eggs', 'high', 'Refrigerated storage as labelled', 'Maintain the cold chain and record use-by dates when receiving stock.'),
    ('meat-seafood', 'Meat & seafood', 'high', 'Refrigerated or frozen storage as labelled', 'Keep raw products separated from ready-to-eat food and follow labelled temperature limits.'),
    ('bakery', 'Bakery', 'high', 'Dry, covered storage; chill filled products', 'Use short stock rotations and protect products from moisture and contamination.'),
    ('grains', 'Grains & pulses', 'low', 'Cool, dry, sealed storage', 'Keep containers sealed, off the floor and away from moisture.'),
    ('frozen', 'Frozen foods', 'low', 'Continuous frozen storage as labelled', 'Keep frozen throughout storage and follow product guidance after thawing.'),
    ('prepared', 'Prepared meals', 'high', 'Temperature-controlled storage as labelled', 'Record preparation and use-by dates and follow your business handling policy.'),
    ('canned', 'Canned & packaged', 'low', 'Cool, dry storage; follow label after opening', 'Inspect seals and packaging and track a revised use-by date after opening if required.'),
    ('beverages', 'Beverages', 'medium', 'Ambient or refrigerated storage as labelled', 'Follow opening and refrigeration instructions on each product.'),
]


def seed(apps, schema_editor):
    Category = apps.get_model('inventory', 'Category')
    for code, name, risk, storage, guidance in TAXONOMY:
        Category.objects.get_or_create(code=code, defaults={'name': name, 'perishability': risk, 'storage': storage, 'guidance': guidance})


class Migration(migrations.Migration):
    dependencies = [('inventory', '0001_initial')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
