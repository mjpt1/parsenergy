# SolarOps

سامانه پایش و مدیریت نیروگاه‌های خورشیدی با معماری ماژولار، API، داشبورد، PWA، گزارش‌ساز و ماژول‌های تحلیل و یادگیری ماشین.

## اجرای محلی
1. ساخت محیط مجازی و نصب وابستگی‌ها از فایل requirements.txt
2. کپی کردن .env.example به .env
3. اجرای migration
4. ایجاد ادمین
5. اجرای سرور توسعه

## ماژول‌ها
- accounts: احراز هویت، نقش‌ها، MFA
- plants: نیروگاه، اینورتر، سنسور، کنتور
- monitoring: داده‌های لحظه‌ای، تله‌متری، WebSocket/SSE
- alerts: آستانه‌ها و اعلان‌ها
- analytics: KPI، مالی، راندمان، افت تولید
- reports: PDF و Excel
- ml: پیش‌بینی تولید، تشخیص خطا، پیشنهاد تعمیر
- api: REST API و مستندات OpenAPI
- pwa: manifest و service worker
- requests: درخواست مشتری، پیشنهاد قیمت، قرارداد، پرداخت داخلی، OTP و پیامک

## دوزبانه و تقویم دوگانه
- رابط کامل **انگلیسی/فارسی** (i18n) با سوییچر زبان و RTL↔LTR خودکار. منبع ترجمه: کاتالوگ `locale/en` که با `python scripts/build_en_catalog.py` ساخته می‌شود (بدون نیاز به gettext).
- **تقویم شمسی/میلادی**: ذخیره‌سازی میلادی، تبدیل در لایه‌ی نمایش با `jdatetime` و فیلترهای `smartdate`/`smartdatetime`.

## استقرار و مستندات
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — استقرار با Docker (Postgres + Redis + Gunicorn/ASGI + Celery + Nginx)
- [docs/SERVER_INSTALL.md](docs/SERVER_INSTALL.md) — نصب روی سرور Ubuntu بدون Docker
- [docs/API.md](docs/API.md) — مستندات REST API (و `/api/docs/` به‌صورت تعاملی)

## نکته
- توسعه‌ی محلی روی **SQLite** و بدون Redis اجرا می‌شود (کش/کانال‌ها in-memory). در production با تنظیم `DATABASE_URL` و `USE_REDIS_*` به Postgres + Redis سوییچ می‌کند.