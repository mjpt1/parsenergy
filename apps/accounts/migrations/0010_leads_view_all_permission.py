from django.db import migrations


def add_permission(apps, schema_editor):
    apps.get_model('accounts', 'Permission').objects.get_or_create(
        code='leads.view_all', defaults={'description': 'مشاهدهٔ همهٔ لیدها (کارشناس ارشد بازار)'})


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_alter_user_role'),
    ]

    operations = [
        migrations.RunPython(add_permission, migrations.RunPython.noop),
    ]
