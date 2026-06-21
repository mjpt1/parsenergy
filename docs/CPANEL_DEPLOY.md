# استقرار روی هاست cPanel (با Terminal)

این راهنما پروژه را روی یک هاست **cPanel** که قابلیت **«Setup Python App»** (Passenger) و **Terminal** دارد مستقر می‌کند.

## معماری روی cPanel
- اجرا با **Passenger (WSGI)** — نه ASGI/Gunicorn/Docker.
- فایل‌های **static** را خودِ اپ با **WhiteNoise** سرو می‌کند (نیازی به Nginx نیست).
- فایل‌های **media/آپلودها** را با `SERVE_MEDIA=True` خود Django سرو می‌کند.
- پایگاه‌داده پیش‌فرض **SQLite** است (ساده‌ترین). گزینهٔ **MySQL** هم هست.
- **Redis/Celery لازم نیست** (به‌صورت پیش‌فرض غیرفعال‌اند و کد بدون آن‌ها بوت می‌شود).

### چه چیزی کار می‌کند و چه چیزی نه
- ✅ همهٔ بخش‌ها: فرم ارزیابی، احراز هویت شاهکار، قراردادها، پرداخت، تیکت، پنل ادمین/کاربر، API، دو‌زبانه و تقویم جلالی، داشبوردها (با polling هر ۳۰ ثانیه).
- ⚠️ تنها چیزی که زیر WSGI غیرفعال می‌شود: **تله‌متری زندهٔ WebSocket** در ماژول monitoring (در رابط کاربری استفاده نشده، پس چیزی نمی‌شکند).

---

## پیش‌نیازها
- دسترسی cPanel با آیکن‌های **Setup Python App** و **Terminal**.
- یک دامنه یا ساب‌دامنه که به هاست اشاره می‌کند.
- نسخهٔ Python در cPanel: **۳٫۱۱ یا ۳٫۱۲** (۳٫۱۰ هم کار می‌کند).

---

## گام ۱ — آپلود کد
از **Terminal** (یا File Manager) کد را در خانهٔ کاربری بگذارید، مثلاً در `~/parsenergy`:

```bash
cd ~
git clone <repo-url> parsenergy      # یا فایل‌ها را با File Manager آپلود کنید
# اگر فقط پوشهٔ solarops را دارید، همان را به‌عنوان ریشهٔ اپ در نظر بگیرید
```

ریشهٔ اپ پوشه‌ای است که داخلش `manage.py`، `passenger_wsgi.py` و پوشهٔ `solarops/` قرار دارد.

## گام ۲ — ساخت Python App
در cPanel → **Setup Python App** → **Create Application**:
- **Python version**: 3.11 یا 3.12
- **Application root**: مسیر ریشهٔ اپ (مثلاً `parsenergy`)
- **Application URL**: دامنه/ساب‌دامنهٔ موردنظر
- Create را بزنید.

cPanel یک **virtualenv** و یک `passenger_wsgi.py` می‌سازد. بالای همان صفحه یک دستور
`source .../bin/activate` نشان می‌دهد — آن را نگه دارید (گام ۴).

## گام ۳ — `passenger_wsgi.py`
اگر cPanel فایل خودش را ساخته، محتوای آن را با محتوای `passenger_wsgi.py` این پروژه جایگزین کنید (همین الان در ریشهٔ اپ موجود است و به `solarops.wsgi.application` وصل می‌شود).

## گام ۴ — فعال‌سازی venv و نصب وابستگی‌ها
در **Terminal**، دستور activate که cPanel داد را اجرا کنید، سپس:

```bash
source ~/virtualenv/parsenergy/3.11/bin/activate   # نمونه؛ دستور دقیق را از cPanel کپی کنید
cd ~/parsenergy
pip install --upgrade pip
pip install -r requirements-cpanel.txt
```

> اگر نصب `numpy/pandas/scikit-learn` به‌خاطر محدودیت منابع شکست خورد، با پشتیبانی هاست برای افزایش موقت حافظهٔ build هماهنگ کنید (این‌ها از wheel نصب می‌شوند و معمولاً بدون مشکل‌اند).

## گام ۵ — فایل `.env`
از روی نمونه بسازید و مقداردهی کنید:

```bash
cp .env.cpanel.example .env
# سپس .env را ویرایش کنید (File Manager یا nano):
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"   # برای SECRET_KEY
```

حداقل این‌ها را تنظیم کنید: `SECRET_KEY`، `DEBUG=False`، `ALLOWED_HOSTS`، `CSRF_TRUSTED_ORIGINS`، `SERVE_MEDIA=True`.

## گام ۶ — پایگاه‌داده، استاتیک، ادمین
```bash
python manage.py migrate
python scripts/build_en_catalog.py        # ساخت ترجمهٔ انگلیسی (.mo) — اگر از قبل آپلود شده لازم نیست
python manage.py collectstatic --noinput  # جمع‌آوری static برای WhiteNoise
python manage.py createsuperuser          # ساخت کاربر مدیر
```

## گام ۷ — راه‌اندازی مجدد اپ
هر بار بعد از تغییر کد یا `.env`:
```bash
mkdir -p tmp && touch tmp/restart.txt
```
یا در صفحهٔ Setup Python App دکمهٔ **Restart** را بزنید.

سپس دامنه را باز کنید — باید بالا بیاید. وارد `/admin/` یا پنل شوید.

## گام ۸ — تنظیم سرویس‌ها (پیامک و شاهکار)
وارد پنل ادمین شوید → **🔌 تنظیمات سرویس‌ها**:
- **پیامک**: سرویس را روی «HTTP» بگذارید و آدرس/کلید سرویس پیامک خود را وارد کنید (در غیر این صورت پیامک فقط لاگ می‌شود).
- **شاهکار**: سرویس را روی «شبانیک» بگذارید، **توکن شاهکار** را وارد کنید و فعال کنید.

> **مهم (شاهکار):** شبانیک فقط درخواست از **IP مجاز** را می‌پذیرد. **IP عمومی سرور هاست** را در پنل شبانیک (بخش توسعه‌دهندگان → IP مجاز) ثبت کنید، وگرنه خطای «درخواست از آی‌پی غیرمجاز» می‌گیرید. IP سرور را می‌توانید با این دستور ببینید:
> ```bash
> curl -s https://api.ipify.org; echo
> ```

---

## استفاده از MySQL (اختیاری)
۱) در cPanel → **MySQL Databases** یک دیتابیس و یوزر بسازید و یوزر را به دیتابیس وصل کنید (ALL PRIVILEGES).
۲) درایور را نصب کنید:
```bash
pip install mysqlclient        # اگر build نشد: pip install PyMySQL
```
۳) در `.env`:
```
DATABASE_URL=mysql://cpaneluser_db:PASSWORD@localhost/cpaneluser_dbname
```
۴) اگر به‌جای mysqlclient از **PyMySQL** استفاده کردید، این دو خط را ابتدای `passenger_wsgi.py` (قبل از import اپ) و نیز ابتدای `manage.py` اضافه کنید:
```python
import pymysql
pymysql.install_as_MySQLdb()
```
۵) `python manage.py migrate` را دوباره اجرا کنید.

---

## رفع اشکال
| نشانه | علت / راه‌حل |
|---|---|
| 500 روی همهٔ صفحات | لاگ Passenger را ببینید؛ معمولاً `.env` ناقص یا وابستگی نصب‌نشده. لاگ اپ: `~/parsenergy/logs/app.log` |
| `DisallowedHost` | دامنه را به `ALLOWED_HOSTS` اضافه کنید و Restart. |
| CSRF در فرم‌ها | دامنهٔ `https://...` را به `CSRF_TRUSTED_ORIGINS` اضافه کنید. |
| استایل‌ها نمی‌آیند | `collectstatic` را اجرا و Restart کنید. |
| آپلودها/لوگو ۴۰۴ | `SERVE_MEDIA=True` در `.env` و Restart. |
| حلقهٔ ریدایرکت https | موقتاً `SECURE_SSL_REDIRECT=False`؛ بعد از فعال‌شدن AutoSSL برگردانید به True. |
| شاهکار: «آی‌پی غیرمجاز» | IP سرور را در پنل شبانیک whitelist کنید. |
| خطای نوشتن لاگ | پوشهٔ `logs/` به‌صورت خودکار ساخته می‌شود؛ اگر مجوز نبود: `chmod 755 logs`. |

## به‌روزرسانی نسخه
```bash
cd ~/parsenergy && git pull
source ~/virtualenv/parsenergy/3.11/bin/activate
pip install -r requirements-cpanel.txt
python manage.py migrate
python manage.py collectstatic --noinput
touch tmp/restart.txt
```
