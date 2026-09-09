# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0004_alter_stock_current_price_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='stockcandle',
            name='volume',
            field=models.DecimalField(decimal_places=4, default=0, max_digits=60),
        ),
    ]