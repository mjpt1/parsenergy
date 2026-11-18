"""Where a customer's request stands, in the customer's words.

Staff track a request by department and sales phase; the customer only needs
to know which of six steps they are on and whether anything is waiting on
them. `customer_progress(req)` turns the stored state into exactly that.
"""
from __future__ import annotations

STEPS = ('ثبت درخواست', 'بررسی کارشناسان', 'پیشنهاد قیمت', 'قرارداد', 'پرداخت', 'نصب و راه‌اندازی')

STOPPED = {
    'hold': 'این درخواست فعلاً متوقف شده است. برای ادامه با پشتیبانی تماس بگیرید.',
    'closed': 'این درخواست بسته شده است.',
    'cancelled': 'این درخواست لغو شده است.',
}


def _has_priced_offer(req) -> bool:
    offers = getattr(req, 'offers', None)
    return offers is None or offers.filter(is_active=True, amount__gt=0).exists()


def customer_progress(req) -> dict:
    """{'steps': [{'label', 'state'}], 'note', 'your_turn'} — state is done/now/todo."""
    status, dept = req.status, req.department
    if status in STOPPED:
        return {'steps': [], 'note': STOPPED[status], 'your_turn': False}
    if req.plant_id:
        now, note, yours = 6, 'نیروگاه شما ساخته شده است و تولید آن را در داشبورد می‌بینید.', False
        return {'steps': [{'label': s, 'state': 'done'} for s in STEPS], 'note': note, 'your_turn': yours}
    if status == 'paid' or dept == 'done':
        now, note, yours = 5, 'پرداخت انجام شده است؛ تیم فنی برای نصب با شما هماهنگ می‌کند.', False
    elif status in ('awaiting_payment', 'contract_approved'):
        now, note, yours = 4, 'قرارداد تأیید شد؛ لطفاً پرداخت را انجام دهید.', True
    elif status == 'contract_generated':
        now, note, yours = 3, 'قرارداد آماده است؛ لطفاً آن را بخوانید و تأیید کنید.', True
    elif status == 'offered' and dept != 'technical' and _has_priced_offer(req):
        now, note, yours = 2, 'پیشنهاد قیمت آماده است؛ لطفاً آن را بررسی و انتخاب کنید.', True
    elif status == 'offered' and dept != 'technical':
        now, note, yours = 2, 'کارشناس فروش در حال نهایی‌کردن مبلغ پیشنهاد است.', False
    elif dept == 'technical':
        now, note, yours = 2, 'کارشناسان فنی در حال آماده‌کردن پیشنهاد هستند.', False
    else:
        now, note, yours = 1, 'درخواست شما ثبت شد؛ کارشناسان ما به‌زودی با شما تماس می‌گیرند.', False
    steps = [{'label': s, 'state': 'done' if i < now else 'now' if i == now else 'todo'}
             for i, s in enumerate(STEPS)]
    return {'steps': steps, 'note': note, 'your_turn': yours, 'current': STEPS[now]}
