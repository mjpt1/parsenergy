# Generated manually for PVModule layout heat-map

from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('plants', '0004_alter_realtimemeasurement_timestamp'),
    ]

    operations = [
        migrations.AddField(
            model_name='plant',
            name='layout_cols',
            field=models.PositiveSmallIntegerField(default=12),
        ),
        migrations.AddField(
            model_name='plant',
            name='layout_rows',
            field=models.PositiveSmallIntegerField(default=8),
        ),
        migrations.CreateModel(
            name='PVModule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('row', models.PositiveSmallIntegerField()),
                ('col', models.PositiveSmallIntegerField()),
                ('code', models.CharField(blank=True, max_length=64)),
                ('string_code', models.CharField(blank=True, max_length=32)),
                ('status', models.CharField(choices=[('ok', 'عادی'), ('warn', 'هشدار دما'), ('hot', 'داغ'), ('offline', 'آفلاین'), ('fault', 'Fault')], default='ok', max_length=16)),
                ('temperature_c', models.DecimalField(decimal_places=2, default=Decimal('40'), max_digits=8)),
                ('relative_power_pct', models.DecimalField(decimal_places=2, default=Decimal('100'), max_digits=6)),
                ('last_seen_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('inverter', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='modules', to='plants.inverter')),
                ('plant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='modules', to='plants.plant')),
            ],
            options={
                'ordering': ['row', 'col'],
                'indexes': [
                    models.Index(fields=['plant', 'status'], name='plants_pvmo_plant_i_status_idx'),
                    models.Index(fields=['plant', 'row', 'col'], name='plants_pvmo_plant_row_col_idx'),
                ],
                'unique_together': {('plant', 'row', 'col')},
            },
        ),
    ]
