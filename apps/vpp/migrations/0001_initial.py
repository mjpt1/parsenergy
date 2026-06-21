from django.db import migrations, models
import django.db.models.deletion
import decimal
from django.conf import settings


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('plants', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='VPP',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='vpps', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='VPPMember',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('contribution_kw', models.DecimalField(decimal_places=2, default=decimal.Decimal('0'), max_digits=12)),
                ('is_active', models.BooleanField(default=True)),
                ('plant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='vpp_memberships', to='plants.plant')),
                ('vpp', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='members', to='vpp.vpp')),
            ],
            options={
                'unique_together': {('vpp', 'plant')},
            },
        ),
        migrations.CreateModel(
            name='DispatchSchedule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_time', models.DateTimeField()),
                ('end_time', models.DateTimeField()),
                ('target_power_kw', models.DecimalField(max_digits=12, decimal_places=2)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('vpp', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='schedules', to='vpp.vpp')),
            ],
        ),
    ]
