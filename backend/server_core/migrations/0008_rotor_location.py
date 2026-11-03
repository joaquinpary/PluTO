import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('server_core', '0007_dispatchorder_reason_stopped'),
    ]

    operations = [
        migrations.AddField(
            model_name='rotor',
            name='latitude_deg',
            field=models.FloatField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(-90.0), django.core.validators.MaxValueValidator(90.0)]),
        ),
        migrations.AddField(
            model_name='rotor',
            name='longitude_deg',
            field=models.FloatField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(-180.0), django.core.validators.MaxValueValidator(180.0)]),
        ),
        migrations.AddField(
            model_name='rotor',
            name='altitude_m',
            field=models.FloatField(blank=True, help_text='Metres above sea level. Empty counts as 0.', null=True),
        ),
    ]
