from django.db import migrations

STEPS = [
    {
        'order': 1, 'label': 'نوع درخواست', 'condition': [],
        'fields': [
            dict(order=1, key='request_type', field_type='radio', label='چه نوع درخواستی دارید؟', required=True),
        ],
    },
    {
        'order': 2, 'label': 'مشخصات و موقعیت', 'condition': [],
        'fields': [
            dict(order=1, key='user_type', field_type='radio', label='نوع کاربر'),
            dict(order=2, key='full_name', field_type='text', label='نام شخصیت حقیقی / حقوقی', required=True),
            dict(order=3, key='province', field_type='select', label='استان', required=True),
            dict(order=4, key='city', field_type='select', label='شهر'),
            dict(order=5, key='install_address', field_type='text', label='آدرس محل نصب'),
            dict(order=6, key='latitude', field_type='text', label='موقعیت روی نقشه (اختیاری)'),
            dict(order=7, key='longitude', field_type='text', label='طول جغرافیایی'),
        ],
    },
    {
        'order': 3, 'label': 'جزئیات مشارکت',
        'condition': [[{'field': 'request_type', 'value': 'partnership'}]],
        'fields': [
            dict(order=1, key='partnership_type', field_type='radio', label='نوع مشارکت شما'),
            dict(order=2, key='investment_range', field_type='radio', label='میزان سرمایهٔ مدنظر شما',
                 condition=[[{'field': 'partnership_type', 'value': 'investment'}]]),
        ],
    },
    {
        'order': 4, 'label': 'مشخصات فنی محل',
        'condition': [
            [{'field': 'request_type', 'value': 'dedicated'}],
            [{'field': 'request_type', 'value': 'partnership'}, {'field': 'partnership_type', 'value': 'space'}],
        ],
        'fields': [
            dict(order=1, key='install_location', field_type='radio', label='مشخصات محل نصب'),
            dict(order=2, key='area_range', field_type='radio', label='مساحت تقریبی فضای نصب'),
            dict(order=3, key='shade_status', field_type='radio', label='آیا محل نصب سایه یا مانعی دارد؟'),
            dict(order=4, key='building_type', field_type='select', label='نوع ساختمان'),
            dict(order=5, key='bill_id', field_type='text', label='شناسهٔ قبض برق (۱۳ رقمی)'),
        ],
    },
    {
        'order': 5, 'label': 'گزینه‌های تکمیلی',
        'condition': [[{'field': 'request_type', 'value': 'dedicated'}]],
        'fields': [
            dict(order=1, key='needs_financial_consult', field_type='yesno', label='آیا نیازی به مشاورهٔ مالی دارید؟'),
            dict(order=2, key='storage_interest', field_type='radio', label='تمایل به سیستم ذخیره‌سازی؟'),
            dict(order=3, key='grid_distance_m', field_type='number', label='فاصله تا شبکهٔ سراسری (متر)'),
        ],
    },
    {
        'order': 6, 'label': 'تماس و تأیید', 'condition': [],
        'fields': [
            dict(order=1, key='description', field_type='textarea', label='توضیحات تکمیلی'),
            dict(order=2, key='contact_method', field_type='radio', label='روش تماس ترجیحی شما', required=True),
            dict(order=3, key='how_heard', field_type='select', label='چگونه با پارس انرژی آشنا شدید؟'),
            dict(order=4, key='utm_source', field_type='text', label='utm_source'),
            dict(order=5, key='utm_medium', field_type='text', label='utm_medium'),
            dict(order=6, key='utm_campaign', field_type='text', label='utm_campaign'),
            dict(order=7, key='utm_content', field_type='text', label='utm_content'),
            dict(order=8, key='utm_term', field_type='text', label='utm_term'),
            dict(order=9, key='campaign_name', field_type='text', label='campaign_name'),
            dict(order=10, key='medium', field_type='text', label='medium'),
            dict(order=11, key='landing_page', field_type='text', label='landing_page'),
            dict(order=12, key='referrer', field_type='text', label='referrer'),
            dict(order=13, key='device_type', field_type='text', label='device_type'),
            dict(order=14, key='first_visit_at', field_type='text', label='first_visit_at'),
            dict(order=15, key='mobile', field_type='text', label='شماره موبایل', required=True),
            dict(order=16, key='national_id', field_type='text', label='کد ملی', required=True),
            dict(order=17, key='accepted_terms', field_type='yesno',
                 label='قوانین و مقررات را مطالعه کرده و می‌پذیرم.', required=True),
        ],
    },
]


def seed(apps, schema_editor):
    FormStep = apps.get_model('requests', 'RequestFormStep')
    FormField = apps.get_model('requests', 'RequestFormField')
    for step_def in STEPS:
        step = FormStep.objects.create(
            order=step_def['order'], label=step_def['label'], condition=step_def['condition'],
        )
        for f in step_def['fields']:
            FormField.objects.create(
                step=step,
                order=f['order'],
                key=f['key'],
                field_type=f['field_type'],
                label=f['label'],
                required=f.get('required', False),
                condition=f.get('condition', []),
                is_system=True,
            )


def unseed(apps, schema_editor):
    apps.get_model('requests', 'RequestFormStep').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('requests', '0017_request_form_builder'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
