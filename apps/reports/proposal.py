"""Preliminary commercial proposal: form data in, 5 A4 pages of HTML out (the browser prints them to PDF)."""
import base64
import io

from PIL import Image, ImageOps

FA = str.maketrans("0123456789,.", "۰۱۲۳۴۵۶۷۸۹٬٫")
MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def image_uri(upload, w=1500):
    """Uploaded photo -> small JPEG data URI, so the page needs no stored files."""
    img = ImageOps.exif_transpose(Image.open(upload)).convert("RGB")
    img.thumbnail((w, w))
    b = io.BytesIO()
    img.save(b, "JPEG", quality=84)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def fa(x):
    return str(x).translate(FA)


def rial(n):
    return fa(f"{n:,}")




def chart(values):
    """Monthly production bars as inline SVG, right-to-left from Farvardin."""
    w, h, top, base = 520, 210, 24, 175
    mx = max(values) * 1.15
    step = w / 12
    out = [f'<svg viewBox="0 0 {w} {h + 10}" class="chart">',
           '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2fa35a"/>'
           '<stop offset="1" stop-color="#0d5f33"/></linearGradient></defs>']
    for t in range(0, 5):
        y = base - (base - top) * t / 4
        out.append(f'<line x1="0" x2="{w}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>')
        out.append(f'<text x="{w}" y="{y - 3:.1f}" class="ax" text-anchor="end">{fa(round(mx * t / 4, 1))}</text>')
    peak = values.index(max(values))
    for i, v in enumerate(values):
        x = w - (i + 1) * step + step * 0.2
        bh = (base - top) * v / mx
        cls = "bar peak" if i == peak else "bar"
        out.append(f'<rect x="{x:.1f}" y="{base - bh:.1f}" width="{step * 0.6:.1f}" height="{bh:.1f}" rx="5" class="{cls}"/>')
        out.append(f'<text x="{x + step * 0.3:.1f}" y="{base - bh - 5:.1f}" class="val" text-anchor="middle">{fa(v)}</text>')
        out.append(f'<text x="{x + step * 0.3:.1f}" y="{base + 16}" class="mon" text-anchor="middle">{MONTHS[i]}</text>')
    out.append("</svg>")
    return "".join(out)


def render(d, logo, cover_url):
    """Return the 5 pages as HTML. String values in d must already be escaped."""
    LOGO = f'<img src="{logo}" alt="Pars Energy">'
    head = f"""<header class="hdr"><div class="brand">{LOGO}<span>PARS ENERGY</span></div>
      <div class="ref"><b>{d['customer']}</b> · {d['location']}<br><span>شماره سند {d['doc_no']}</span></div></header>"""

    def page(n, footer, body):
        return (f'<section class="page">{head}<main>{body}</main><footer><span>{footer}</span>'
                f'<span class="pn">صفحه {fa(n)} از ۵</span><span>pars-energy.com</span></footer></section>')

    kicker = lambda k, t, s="": f'<div class="kicker">{k}</div><h2>{t}</h2>' + (f'<p class="sub">{s}</p>' if s else "")
    stat = lambda label, value, unit, note, hl="": (f'<div class="stat {hl}"><span>{label}</span><b>{value}<small>{unit}</small></b>'
                                                    f'<em>{note}</em></div>')

    cover = f"""<section class="page cover">
      <div class="cv-top">
        <div class="cv-meta">شماره سند: <b>{d['doc_no']}</b><br>تاریخ صدور: <b>{fa(d['date'])}</b><br>اعتبار برآورد قیمت: <b>۷ روز تقویمی</b></div>
        <div class="brand big">{LOGO}<span>PARS ENERGY</span></div>
      </div>
      <div class="cv-title"><div class="eyebrow">PRELIMINARY COMMERCIAL PROPOSAL</div>
        <h1>پیشنهاد تجاری اولیه<br>نیروگاه خورشیدی</h1>
        <div class="cv-client">{d['customer']}<br><span>{d['location']}</span></div>
        <p>برآورد اولیه برای تصمیم‌گیری و ورود به مرحله ارزیابی فنی</p>
        <div class="cv-kpis"><div><b>{fa(d['kwp'])}</b>kWp ظرفیت</div><div><b>{fa(d['mwh'])}</b>MWh تولید سالانه</div><div><b>{fa(d['modules'])}</b>ماژول</div></div>
      </div>
      <div class="cv-photo" style="background-image:url({cover_url})"></div>
    </section>"""

    p2 = page(2, "پیشنهاد تجاری اولیه", f"""
      <div class="intro"><b>پارس انرژی</b> پروژه‌های خورشیدی را بر اساس شرایط هر سایت و هدف مشتری بررسی می‌کند. این سند بر پایه اطلاعات اولیه پروژه تهیه شده تا تصویری روشن از ظرفیت، وضعیت فنی، برآورد اقتصادی و مسیر ادامه کار ارائه دهد.</div>
      {kicker('تصویر اولیه پروژه', f'پروژه {d["customer"]} در یک نگاه',
              f'بر اساس اطلاعات اولیه دریافت‌شده، احداث نیروگاه خورشیدی در {d["site_desc"]} با ظرفیت تقریبی <b>{fa(d["kwp"])} kWp</b> قابل بررسی است. ظرفیت نهایی و مدل همکاری پس از تکمیل مرحله اول مشخص می‌شود.')}
      <div class="stats">
        {stat('مرحله فعلی پروژه', 'ارزیابی اولیه', '', 'پیش از بازدید فنی')}
        {stat('نوع محل نصب', d['site_type'], '', d['site_note'])}
        {stat('تولید سالانه تخمینی', fa(d['mwh']), 'MWh', 'بر اساس شبیه‌سازی اولیه')}
        {stat('ظرفیت اولیه قابل بررسی', fa(d['kwp']), 'kWp', 'بر اساس اطلاعات فعلی', 'hl')}
      </div>
      <div class="photos">
        <figure><img src="{d['layout']}"><figcaption>جانمایی اولیه پنل‌ها</figcaption></figure>
        <figure><img src="{d['site']}"><figcaption>تصویر واقعی محل پروژه</figcaption></figure>
      </div>
      <div class="card">
        <h3>مدل همکاری بعد از مرحله اول مشخص می‌شود</h3>
        <p>بازدید، ارزیابی و طراحی اولیه مشخص می‌کند چه سناریویی برای پروژه مناسب‌تر است. پارس انرژی در مرحله دوم، بر اساس نتیجه بررسی فنی و شرایط مشتری، یک یا چند گزینه قابل اجرا ارائه می‌کند.</p>
        <div class="chips"><span>اختصاصی</span><span>مشارکتی</span><span>اجاره فضا</span></div>
        <p class="fine">انتخاب نهایی مدل همکاری در مرحله دوم و با توافق طرفین انجام می‌شود.</p>
      </div>
      <div class="cta"><span>گام مورد انتظار در این مرحله</span><b>ورود به مرحله اول: ارزیابی، بازدید و طراحی</b>
        <p>این پیشنهاد قرارداد اجرا نیست. با تأیید آن، مرحله اول برای بررسی دقیق‌تر پروژه آغاز می‌شود.</p></div>""")

    spec = lambda k, v: f'<div><span>{k}</span><b>{v}</b></div>'
    p3 = page(3, "تحلیل فنی اولیه", f"""
      {kicker('تحلیل فنی اولیه', 'طرح فنی اولیه بر مبنای اطلاعات موجود',
              'اعداد این صفحه بر پایه اطلاعات فعلی و شبیه‌سازی اولیه هستند. پس از بازدید سایت و بررسی سازه، سایه‌اندازی، مسیر کابل‌کشی و نقطه اتصال، طراحی به‌روزرسانی می‌شود.')}
      <div class="specs">
        {spec('ماژول خورشیدی', f'{fa(d["modules"])} × {fa(d["wp"])} Wp')}{spec('اینورتر', f'{fa(d["inv_n"])} × {fa(d["inv_kw"])} kWac')}
        {spec('نسبت عملکرد اولیه (PR)', f'{fa(d["pr"])}٪')}{spec('تولید سالانه', f'{fa(d["mwh"])} MWh')}
        {spec('بیشترین تولید ماهانه', f'{fa(max(d["monthly"]))} MWh')}{spec('کمترین تولید ماهانه', f'{fa(min(d["monthly"]))} MWh')}
      </div>
      <div class="card chartcard"><div class="ch-h"><h3>نمودار تولید ماهانه</h3><span>منبع تحلیل: <b>{d['tool']}</b> · واحد MWh</span></div>{chart(d['monthly'])}</div>
      <div class="two">
        <div class="card soft"><h3>پس از ارزیابی نهایی می‌شود</h3><p>ظرفیت قابل اجرا، تجهیزات منتخب، طراحی نهایی، برآورد تولید به‌روز، قیمت قطعی و شرایط اجرایی پروژه.</p></div>
        <div class="card"><h3>در ارزیابی فنی بررسی می‌شود</h3><p>سازه و محدودیت‌های اجرایی، جانمایی واقعی پنل‌ها، سایه‌اندازی، مسیرهای کابل‌کشی، محل اتصال و الزامات بهره‌برداری.</p></div>
      </div>
      <div class="cta slim">خروجی مورد انتظار: <b>پیشنهاد نهایی فنی و تجاری قابل قرارداد</b></div>""")

    value = round(d["mwh"] * 1000) * d["rate"]
    p4 = page(4, "اقتصاد پروژه - ارزیابی اولیه", f"""
      {kicker('اقتصاد پروژه - سال اول', 'اعداد اصلی برای تصمیم‌گیری اولیه',
              'در این مرحله فقط اعدادی درج شده‌اند که با اطلاعات فعلی قابل محاسبه‌اند. سناریوی اقتصادی هر مدل همکاری پس از تکمیل مرحله اول ارائه می‌شود.')}
      <div class="money">
        <div class="hl"><span>ارزش ناخالص انرژی در سال اول</span><b>{rial(value)}</b><small>ریال در سال</small>
          <em>مبنای محاسبه: تولید سالانه تخمینی × نرخ مرجع ثبت‌شده</em></div>
        <div><span>برآورد اولیه هزینه احداث پروژه</span><b>{rial(d['capex'])}</b><small>ریال</small>
          <em>این عدد مقیاس تقریبی هزینه احداث را نشان می‌دهد و به معنی تعیین سهم سرمایه‌گذاری مشتری نیست.</em></div>
      </div>
      <div class="card"><h3>فرضیات و مبنای محاسبه</h3><ul class="facts">
        <li>تولید سالانه مبنا: <b>{rial(round(d['mwh'] * 1000))} kWh</b></li><li>منبع نرخ: <b>{d['rate_src']}</b></li>
        <li>نرخ مرجع برق: <b>{rial(d['rate'])} ریال/kWh</b></li><li>عدد سال اول، سود خالص یا تضمین درآمد نیست.</li>
        <li>تاریخ نرخ: <b>{fa(d['rate_date'])}</b></li><li>هزینه‌های بهره‌برداری، بیمه و مالیات در این عدد لحاظ نشده‌اند.</li></ul></div>
      <div class="two">
        <div class="stat"><span>واحد قیمت‌گذاری</span><b>ریال</b><em>تمام مبالغ مشتری در این پیشنهاد به ریال ثبت می‌شوند.</em></div>
        <div class="stat hl"><span>اعتبار برآورد قیمت</span><b>۷ روز تقویمی</b><em>از تاریخ صدور این پیشنهاد</em></div>
      </div>
      <div class="notice"><b>وضعیت قیمت:</b> برآورد بودجه‌ای / تقریبی. قیمت قطعی پس از ارزیابی فنی، نهایی‌شدن تجهیزات و دامنه اجرایی در پیشنهاد نهایی اعلام می‌شود.</div>""")

    steps = ["تأیید پیشنهاد اولیه", "قرارداد مرحله اول و پرداخت هزینه خدمات", "بازدید و ارزیابی فنی",
             "پیشنهاد نهایی فنی و تجاری", "قرارداد مرحله دوم", "اجرا، راه‌اندازی و تحویل"]
    docs = ["As-Built Drawings", "Final Equipment List", "Datasheets", "Serial Numbers", "Commissioning Records", "O&M Information", "ثبت گارانتی و پشتیبانی"]
    p5 = page(5, "گام بعد و شرایط ادامه", f"""
      {kicker('گام بعد و شرایط ادامه', 'از تأیید اولیه تا پیشنهاد نهایی و اجرا')}
      <ol class="timeline">{''.join(f'<li class="{"on" if i < 2 else ""}"><b>{fa(i + 1)}</b><span>{s}</span></li>' for i, s in enumerate(steps))}</ol>
      <div class="two">
        <div class="card"><h3>خدمات مرحله اول: ارزیابی، بازدید و طراحی</h3>
          <p class="fine">مبلغ زیر بهای خدمات مرحله اول است و پس از انعقاد قرارداد مرحله اول و پیش از شروع خدمات دریافت می‌شود.</p>
          <div class="fee"><span>هزینه خدمات مرحله اول</span><b>{rial(d['phase1_fee'])} <small>ریال</small></b></div>
          <ul class="ticks"><li>بررسی اطلاعات و مدارک اولیه</li><li>بازدید و بررسی واقعی سایت و محدودیت‌ها</li>
            <li>کنترل جانمایی، سایه، کابل‌کشی و محل اتصال</li><li>نهایی‌سازی طراحی و پیشنهاد فنی - تجاری</li></ul>
          <p class="fine">اگر پروژه وارد مرحله دوم شود، در مدل اختصاصی این مبلغ یک‌بار از قسط اول قرارداد اجرا کسر می‌شود. در مدل‌های مشارکتی و اجاره فضا، مبلغ پرداخت‌شده به پرداخت‌کننده عودت داده می‌شود.</p></div>
        <div class="card soft"><h3>قرارداد مرحله دوم و اجرای پروژه</h3>
          <p>پس از پایان مرحله اول، نتیجه بررسی فنی مبنای پیشنهاد مرحله دوم قرار می‌گیرد. قرارداد فقط پس از انتخاب و تأیید طرفین منعقد می‌شود.</p>
          <h4>در قرارداد نهایی به‌صورت شفاف تعیین می‌شود:</h4>
          <ul class="ticks"><li>مدل همکاری منتخب: اختصاصی / مشارکتی / اجاره فضا</li><li>ظرفیت و تجهیزات نهایی</li>
            <li>قیمت یا ساختار اقتصادی و زمان‌بندی اجرا</li><li>شرایط پرداخت و مسئولیت‌های اتصال، تحویل و بهره‌برداری</li></ul></div>
      </div>
      <div class="card"><h3>تحویل پرونده نهایی دارایی انرژی</h3>
        <p class="fine">پس از تکمیل پروژه، مدارک نهایی لازم برای بهره‌برداری، نگهداری و رهگیری تجهیزات تحویل می‌شود.</p>
        <div class="chips docs">{''.join(f'<span>{x}</span>' for x in docs)}</div></div>
      <div class="cta dark"><b>گام بعدی: تأیید پیشنهاد و انعقاد قرارداد مرحله اول</b>
        <p>پس از امضای قرارداد مرحله اول و پرداخت هزینه خدمات، زمان بازدید و ارزیابی فنی هماهنگ می‌شود.</p></div>""")

    return cover + p2 + p3 + p4 + p5
