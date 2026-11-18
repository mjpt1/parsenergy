# Generated manually for Ticket.Department marketing + operations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('requests', '0015_website_lead_workflow'),
    ]

    operations = [
        migrations.AlterField(
            model_name='ticket',
            name='department',
            field=models.CharField(
                choices=[
                    ('sales', 'فروش'),
                    ('technical', 'فنی'),
                    ('marketing', 'بازاریابی'),
                    ('operations', 'عملیات'),
                    ('management', 'مدیریت'),
                ],
                db_index=True,
                default='sales',
                max_length=16,
            ),
        ),
    ]
