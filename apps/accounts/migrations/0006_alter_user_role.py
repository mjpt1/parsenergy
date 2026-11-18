# Generated manually for website lead workflow roles

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_user_extra_permissions'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('owner', 'Owner'),
                    ('admin', 'مدیریت'),
                    ('operator', 'Operator'),
                    ('analyst', 'Analyst'),
                    ('marketing', 'توسعه بازار'),
                    ('sales', 'فروش'),
                    ('technical', 'فنی'),
                    ('operations', 'عملیات'),
                    ('customer', 'مشتری'),
                ],
                default='owner',
                max_length=20,
            ),
        ),
    ]
