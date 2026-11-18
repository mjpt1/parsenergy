from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0003_lead_country_reminders'),
    ]

    operations = [
        migrations.AddField(
            model_name='lead',
            name='demand_power',
            field=models.CharField(
                blank=True, max_length=16, verbose_name='توان مورد تقاضا',
                choices=[('under_1mw', 'زیر یک مگاوات'),
                         ('over_1mw', 'بیشتر از یک مگاوات'),
                         ('unknown', 'نمی‌دانم')]),
        ),
        migrations.AlterField(
            model_name='lead',
            name='timeline',
            field=models.CharField(
                blank=True, max_length=16,
                verbose_name='زمان احتمالی تصمیم‌گیری یا شروع پروژه',
                choices=[('lt_1m', 'کمتر از ۱ ماه'), ('m1_3', '۱ تا ۳ ماه'),
                         ('m3_6', '۳ تا ۶ ماه'), ('gt_6m', 'بیش از ۶ ماه'),
                         ('exploring', 'فعلاً در حال بررسی')]),
        ),
    ]
