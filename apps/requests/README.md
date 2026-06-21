# ماژول مدیریت درخواست‌ها (`apps.requests`)

زیرسیستم ثبت درخواست مشتری، پیشنهاد قیمت، قرارداد، پرداخت و پیامک — به‌صورت یک ماژول داخلی در همان سیستم SolarOps (بدون وردپرس/ووکامرس). این ماژول از Layout، احراز هویت، RBAC و قالب پایه‌ی (`base.html`) موجود استفاده می‌کند و پنل جدیدی نمی‌سازد.

## ساختار

```
apps/requests/
├── models.py            # ۷ مدل دامنه
├── repositories.py      # لایه دسترسی داده + scope کاربر
├── services/
│   ├── lifecycle.py     # state machine + transition()
│   ├── offers.py        # قانون حداکثر ۳ پیشنهاد، toggle، انتخاب
│   ├── contracts.py     # تولید قرارداد + تأیید با OTP
│   ├── otp.py           # صدور/اعتبارسنجی کد یک‌بارمصرف
│   ├── sms.py           # SMS abstraction (Console / Http)
│   └── payments.py      # Payment Service داخلی + callback
├── serializers.py / api_views.py / api_urls.py   # REST API (زیر /api/)
├── views_admin.py       # صفحات داخل پنل ادمین موجود (/requests/manage/)
├── views_user.py        # پنل کاربر «درخواست‌های من» (/requests/…)
├── forms.py             # فرم ثبت درخواست و تکمیل پروفایل
└── tests/               # ۲۷ تست (services + flow)
templates/requests/{admin,user}/   # همه با {% extends 'base.html' %}
```

## مدل‌ها
`Request` · `RequestOffer` · `RequestContract` · `RequestPayment` · `OtpVerification` · `RequestMessageLog` · `UserProfileCompletion`
(جزئیات فیلدها در `models.py`؛ FKهای کاربر از `settings.AUTH_USER_MODEL`.)

## چرخه‌ی وضعیت (`lifecycle.ALLOWED_TRANSITIONS`)

```
new → offered → contract_generated → contract_approved → awaiting_payment → paid
(هر مرحله → cancelled)
```
تنها مرجع تغییر وضعیت `lifecycle.transition()` است که گذار را اعتبارسنجی، در `AuditLog` ثبت و پیامک تغییر وضعیت ارسال می‌کند.

## نگاشت قوانین کسب‌وکار
| قانون | محل |
|---|---|
| حداکثر ۳ پیشنهاد | `offers.add_offer` |
| پیشنهاد منقضی غیرقابل‌پرداخت | `offers.is_payable` / `payments.create_for_offer` |
| بدون تأیید قرارداد پرداخت ممنوع | `payments.create_for_offer` |
| پرداخت موفق → status=paid | `payments.handle_callback` |
| ثبت‌نام تکراری با موبایل ممنوع | `views_user`/`api_views` (چک `username=mobile`) |
| لاگ همه‌ی تغییرات و پیامک‌ها | `AuditLog` + `RequestMessageLog` |

## API (زیر `/api/`)
`requests/` · `requests/{id}/{offers,select-offer,contract,contract/request-otp,contract/approve,messages}` ·
`request-offers/` (+`{id}/toggle`) · `request-contracts/` · `request-payments/` · `request-message-logs/` (مدیر) ·
`request-otp/request/` · `request-otp/verify/`

## پنل ادمین (`/requests/manage/`)
لیست (فیلتر وضعیت/استان/تاریخ) · جزئیات (ثبت/فعال‌سازی پیشنهاد، تغییر وضعیت، قرارداد، پرداخت‌ها، لاگ پیامک) ·
زیرمنوها: پیشنهادها / پرداخت‌ها / قراردادها / لاگ پیامک. محافظت: `requests.manage` (یا superuser/role=admin).

## پنل کاربر (`/requests/`)
`submit/` (عمومی) → `verify/` (OTP) → `mine/` · `mine/{id}/` · انتخاب پیشنهاد · `contract/` (تأیید با OTP) ·
`mine/{id}/pay/` → درگاه داخلی `pay/{token}/` → `pay/{token}/callback/` · `messages/` · `profile/complete/`.

## پیکربندی پیامک (از طریق `SystemParameter`)
`sms_provider` (`console`|`http`) · `sms_enabled` · `sms_base_url` · `sms_api_key` (سکرت) · `sms_sender`.
پیش‌فرض `console` است (در dev، کد/پیام در کنسول چاپ و در `RequestMessageLog` ثبت می‌شود).

## پرداخت
`InternalPaymentBackend` یک درگاه داخلی توکن‌محور با callback است؛ پرداخت مستقیماً به `RequestOffer` متصل می‌شود. کلاس `PaymentBackend` امکان افزودن درگاه واقعی در آینده را می‌دهد.

## اجرای تست‌ها
```
python manage.py test apps.requests
```
