# Website lead workflow: marketing pipeline, UTM, CRM handoff, hold/closed

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def forwards_pipeline(apps, schema_editor):
    Request = apps.get_model('requests', 'Request')
    now = timezone.now()
    # Legacy manager queue → marketing
    Request.objects.filter(department='manager').update(
        department='marketing', sales_phase='', stage_entered_at=now)
    # Technical with offers already priced → sales negotiation
    for req in Request.objects.filter(department='technical').iterator():
        if req.offers.exists() if hasattr(req, 'offers') else False:
            pass
    # Use through table / related: check offers via Offer model
    Offer = apps.get_model('requests', 'RequestOffer')
    priced_ids = set(Offer.objects.values_list('request_id', flat=True).distinct())
    Request.objects.filter(department='technical', id__in=priced_ids).update(
        department='sales', sales_phase='negotiation', stage_entered_at=now)
    Request.objects.filter(department='technical').exclude(id__in=priced_ids).update(
        stage_entered_at=now)
    # Sales queue → qualification unless already has offers from technical
    Request.objects.filter(department='sales', sales_phase='').exclude(
        id__in=priced_ids
    ).update(sales_phase='qualification', stage_entered_at=now)
    Request.objects.filter(department='sales', id__in=priced_ids).update(
        sales_phase='negotiation')
    Request.objects.filter(department='done', crm_transferred=False).update(
        crm_transferred=True, crm_transferred_at=now)
    Request.objects.filter(stage_entered_at__isnull=True).update(stage_entered_at=now)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('requests', '0014_alter_request_department'),
    ]

    operations = [
        migrations.AddField(
            model_name='request',
            name='sales_phase',
            field=models.CharField(
                blank=True, choices=[('qualification', 'صلاحیت‌سنجی'), ('negotiation', 'مذاکره تجاری')],
                db_index=True, max_length=16),
        ),
        migrations.AddField(
            model_name='request',
            name='stage_entered_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='request',
            name='marketing_reviewed_by',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='marketing_reviewed_requests', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='request',
            name='marketing_reviewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='request',
            name='sales_assignee',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='sales_assigned_requests', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='request',
            name='crm_transferred',
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name='request',
            name='crm_transferred_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='request',
            name='crm_transferred_by',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='crm_transferred_requests', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='request',
            name='campaign_name',
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
        migrations.AddField(
            model_name='request',
            name='medium',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='request',
            name='landing_page',
            field=models.CharField(blank=True, max_length=512),
        ),
        migrations.AddField(
            model_name='request',
            name='referrer',
            field=models.CharField(blank=True, max_length=512),
        ),
        migrations.AddField(
            model_name='request',
            name='utm_source',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='request',
            name='utm_medium',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='request',
            name='utm_campaign',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='request',
            name='utm_content',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='request',
            name='utm_term',
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AddField(
            model_name='request',
            name='first_visit_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='request',
            name='device_type',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='request',
            name='how_heard',
            field=models.CharField(
                blank=True,
                choices=[
                    ('google', 'Google'), ('instagram', 'Instagram'), ('linkedin', 'LinkedIn'),
                    ('referral', 'معرفی'), ('exhibition', 'نمایشگاه'), ('sms', 'پیامک'),
                    ('phone', 'تماس تلفنی'), ('other', 'سایر'),
                ],
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name='request',
            name='status',
            field=models.CharField(
                choices=[
                    ('new', 'ثبت‌شده'), ('offered', 'پیشنهاد ثبت شد'),
                    ('contract_generated', 'قرارداد تولید شد'),
                    ('contract_approved', 'قرارداد تأیید شد'),
                    ('awaiting_payment', 'در انتظار پرداخت'), ('paid', 'پرداخت‌شده'),
                    ('hold', 'معلق'), ('closed', 'بسته / از دست‌رفته'),
                    ('cancelled', 'لغو شده'),
                ],
                default='new', max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name='request',
            name='department',
            field=models.CharField(
                choices=[
                    ('marketing', 'بازاریابی'), ('technical', 'فنی'),
                    ('sales', 'فروش'), ('done', 'تکمیل‌شده'),
                ],
                db_index=True, default='marketing', max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name='request',
            name='lead_source',
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddIndex(
            model_name='request',
            index=models.Index(fields=['department', 'sales_phase'], name='requests_re_departm_sales_idx'),
        ),
        migrations.RunPython(forwards_pipeline, noop),
    ]
