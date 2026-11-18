"""Ensure the four working roles exist, and report their state.

The behaviour-driving role is ``User.role`` (a CharField); this command also
seeds matching rows in the ``Role`` table so they show up in the roles UI.

Run:  python manage.py seed_roles
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from apps.accounts.models import Role, Permission

# (User.role value, Role.name, human description)
ROLES = [
    ('admin', 'مدیریت', 'دسترسی کامل و نظارت بر همهٔ بخش‌ها (داشبورد مدیر اجرایی)'),
    ('marketing', 'توسعه بازار', 'کارشناس ارشد توسعه بازار و فروش — بررسی کیفیت لید و کمپین'),
    ('sales', 'فروش', 'کارشناس فروش — تماس، اولویت‌بندی، مذاکره و قرارداد'),
    ('technical', 'فنی', 'کارشناس ارشد فنی — ارزیابی و پیشنهاد فنی (بدون هویت مشتری)'),
    ('operations', 'عملیات', 'کارشناس ارشد عملیات و فرایند — مالکیت Workflow و نظارت Pipeline'),
    ('customer', 'مشتری', 'کاربر مشتری — ثبت و پیگیری درخواست'),
    ('contractor', 'پیمانکار', 'پیمانکار بیرونی — فقط پروژه‌های متصل به خودش'),
]

# Extra access toggles an admin can grant per user (code, human description).
PERMISSIONS = [
    ('admin.access', 'دسترسی مدیریتی (پنل مدیریت)'),
    ('plants.access', 'دسترسی به نیروگاه‌ها و تجهیزات'),
    ('reports.access', 'دسترسی به گزارش‌ها'),
    ('analytics.access', 'دسترسی به تحلیل اقتصادی'),
    ('requests.manage', 'مدیریت کامل درخواست‌ها'),
    ('requests.payments', 'مشاهدهٔ پرداخت‌ها'),
    ('leads.view_all', 'مشاهدهٔ همهٔ لیدها (کارشناس ارشد بازار)'),
]


class Command(BaseCommand):
    help = 'Check that the admin/sales/technical/customer roles exist and create any missing ones.'

    def handle(self, *args, **options):
        User = get_user_model()
        valid_role_values = set(User.Role.values)

        self.stdout.write('بررسی نقش‌ها (User.role choices):')
        for value, name, _desc in ROLES:
            ok = value in valid_role_values
            self.stdout.write(f'  - {name} ({value}): ' + ('موجود ✓' if ok else 'در choices نیست ✗ (نیازمند تغییر کد)'))

        self.stdout.write('\nهمگام‌سازی جدول Role:')
        created_count = 0
        for value, name, desc in ROLES:
            obj, created = Role.objects.get_or_create(
                name=name,
                defaults={'description': desc, 'is_system': True},
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'  + ساخته شد: {name}'))
            else:
                # keep the description / system flag up to date
                changed = False
                if not obj.description:
                    obj.description = desc
                    changed = True
                if not obj.is_system:
                    obj.is_system = True
                    changed = True
                if changed:
                    obj.save(update_fields=['description', 'is_system'])
                self.stdout.write(f'  = از قبل موجود: {name}')

        self.stdout.write('\nهمگام‌سازی مجوزها (Permission):')
        for code, desc in PERMISSIONS:
            obj, created = Permission.objects.get_or_create(
                code=code, defaults={'description': desc})
            if created:
                self.stdout.write(self.style.SUCCESS(f'  + ساخته شد: {code}'))
            else:
                if not obj.description:
                    obj.description = desc
                    obj.save(update_fields=['description'])
                self.stdout.write(f'  = از قبل موجود: {code}')

        self.stdout.write('\nتعداد کاربران به‌تفکیک نقش:')
        for value, name, _desc in ROLES:
            n = User.objects.filter(role=value).count()
            self.stdout.write(f'  - {name} ({value}): {n} کاربر')
        other = User.objects.exclude(role__in=[r[0] for r in ROLES]).count()
        if other:
            self.stdout.write(f'  - سایر نقش‌ها (owner/operator/analyst): {other} کاربر')

        self.stdout.write(self.style.SUCCESS(
            f'\nانجام شد. {created_count} نقش جدید ساخته شد؛ بقیه از قبل موجود بودند.'))
