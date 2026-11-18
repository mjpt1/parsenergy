import re

import jdatetime
from django import forms

MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']
_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫', '01234567890123456789.')
# field -> unit shown beside the input
UNITS = {'kwp': 'kWp', 'mwh': 'MWh', 'modules': 'عدد', 'wp': 'Wp', 'inv_n': 'عدد', 'inv_kw': 'kWac', 'pr': '٪',
         'rate': 'ریال/kWh', 'capex': 'ریال', 'phase1_fee': 'ریال'}
MONEY = ('rate', 'capex', 'phase1_fee')
SECTIONS = [
    ('مشتری و سند', 'روی جلد و سربرگ همهٔ صفحه‌ها می‌آید.', ['customer', 'location', 'doc_no', 'date']),
    ('محل پروژه', 'در صفحهٔ «پروژه در یک نگاه» استفاده می‌شود.', ['site_desc', 'site_type', 'site_note']),
    ('مشخصات فنی', 'از خروجی شبیه‌سازی اولیه.', ['kwp', 'modules', 'wp', 'inv_n', 'inv_kw', 'pr', 'tool']),
    ('تولید انرژی', 'نمودار صفحهٔ ۳ از همین ۱۲ عدد ساخته می‌شود.', ['mwh', 'monthly']),
    ('اقتصاد پروژه', 'همهٔ مبالغ به ریال؛ معادل تومان زیر هر خانه نشان داده می‌شود.', ['rate', 'rate_src', 'rate_date', 'capex', 'phase1_fee']),
    ('تصاویر', 'عکس جلد ثابت است و لازم نیست انتخاب شود.', ['layout', 'site']),
]


def _today():
    return jdatetime.date.today().strftime('%Y/%m/%d')


def _number(value):
    """Persian/Arabic digits and thousands separators -> a plain number string."""
    return re.sub(r'[٬,\s]', '', str(value).translate(_DIGITS))


class ProposalForm(forms.Form):
    customer = forms.CharField(label='نام مشتری / مجموعه', max_length=120)
    location = forms.CharField(label='شهر / استان پروژه', max_length=120)
    doc_no = forms.CharField(label='شماره سند', max_length=60)
    date = forms.CharField(label='تاریخ صدور', max_length=20, initial=_today)
    site_desc = forms.CharField(label='محل پروژه (در متن)', max_length=160, help_text='مثل: سقف کارخانه مامک شمال')
    site_type = forms.ChoiceField(label='نوع محل نصب', choices=[('سقف', 'سقف'), ('زمین', 'زمین')])
    site_note = forms.CharField(label='شرح کوتاه محل', max_length=60, help_text='مثل: سقف سوله تولیدی')
    kwp = forms.DecimalField(label='ظرفیت', min_value=0, decimal_places=2)
    mwh = forms.DecimalField(label='تولید سالانه تخمینی', min_value=0, decimal_places=2)
    modules = forms.IntegerField(label='تعداد ماژول', min_value=1)
    wp = forms.IntegerField(label='توان هر ماژول', min_value=1)
    inv_n = forms.IntegerField(label='تعداد اینورتر', min_value=1)
    inv_kw = forms.DecimalField(label='توان هر اینورتر', min_value=0, decimal_places=2)
    pr = forms.DecimalField(label='نسبت عملکرد (PR)', min_value=0, max_value=100, decimal_places=2)
    tool = forms.CharField(label='ابزار تحلیل', max_length=40, initial='PVsyst')
    monthly = forms.CharField(label='تولید ماهانه (MWh)', widget=forms.HiddenInput)
    rate = forms.IntegerField(label='نرخ مرجع برق', min_value=0)
    rate_src = forms.CharField(label='منبع نرخ', max_length=80, initial='بورس انرژی')
    rate_date = forms.CharField(label='تاریخ نرخ', max_length=20, initial=_today)
    capex = forms.IntegerField(label='برآورد هزینه احداث', min_value=0)
    phase1_fee = forms.IntegerField(label='هزینه خدمات مرحله اول', min_value=0)
    layout = forms.ImageField(label='جانمایی اولیه پنل‌ها')
    site = forms.ImageField(label='عکس واقعی محل پروژه')

    months = MONTHS

    def __init__(self, data=None, *args, **kwargs):
        if data is not None:
            data = data.copy()
            for name in UNITS:
                if data.get(name):
                    data[name] = _number(data[name])
        super().__init__(data, *args, **kwargs)
        for name, f in self.fields.items():
            f.unit = UNITS.get(name, '')
            f.money = name in MONEY
            if name in UNITS:
                # Text, not type=number: browsers refuse Persian digits in number inputs.
                f.widget = forms.TextInput(attrs={'inputmode': 'decimal', 'dir': 'ltr', 'autocomplete': 'off'})
            if isinstance(f, forms.ImageField):
                f.widget.attrs['accept'] = 'image/*'
            f.widget.attrs.setdefault('class', 'form-select' if isinstance(f, forms.ChoiceField) else 'form-control')

    def sections(self):
        return [(title, hint, [self[n] for n in names]) for title, hint, names in SECTIONS]

    def clean_monthly(self):
        raw = self.cleaned_data['monthly'].translate(_DIGITS).replace('،', ',')
        try:
            values = [float(x) for x in re.split(r'[\s,]+', raw) if x]
        except ValueError:
            raise forms.ValidationError('فقط عدد وارد کنید.')
        # A year of zeros has no chart to draw (and would divide by zero).
        if len(values) != 12 or min(values) < 0 or max(values) <= 0:
            raise forms.ValidationError('تولید هر ۱۲ ماه را وارد کنید.')
        return values

    def clean(self):
        data = super().clean()
        # Decimal -> plain number so 124.0 prints as ۱۲۴ and the math stays simple.
        for key in ('kwp', 'mwh', 'inv_kw', 'pr'):
            if data.get(key) is not None:
                v = float(data[key])
                data[key] = int(v) if v.is_integer() else v
        return data
