"""Forms for the two capture stages.

They are plain forms rather than ModelForms because each one writes to two
places: the `Request` that carries the lead through the normal pipeline, and
the `Lead` detail that holds the exhibition-only answers.

Stage one has to be fast: only the name and the mobile number are required,
and every other question is a tap. Stage two asks for project detail and is
entirely optional — a lead with nothing but a phone number is still a lead.
"""
from __future__ import annotations

import re

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.requests.iran_locations import CITIES, COUNTRIES, IRAN, PROVINCES
from apps.requests.models import Request

from .models import Lead

MOBILE_RE = re.compile(r'^09\d{9}$')
BILL_EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png', '.webp', '.zip')
BILL_MAX_BYTES = 10 * 1024 * 1024


def _normalise_mobile(raw: str) -> str:
    """Accept the shapes people actually type: ۰۹…, +989…, 0098 9…, 9…"""
    digits = raw.strip().translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩',
                                                 '01234567890123456789'))
    digits = re.sub(r'\D', '', digits)
    if digits.startswith('0098'):
        digits = '0' + digits[4:]
    elif digits.startswith('98') and len(digits) == 12:
        digits = '0' + digits[2:]
    elif digits.startswith('9') and len(digits) == 10:
        digits = '0' + digits
    return digits


class LeadStageOneForm(forms.Form):
    """Under a minute, on a phone, standing up."""

    full_name = forms.CharField(label=_('نام و نام خانوادگی'), max_length=150)
    mobile = forms.CharField(label=_('شمارهٔ موبایل'))
    company = forms.CharField(label=_('نام شرکت / مجموعه'), max_length=150)
    job_title = forms.CharField(label=_('سمت'), max_length=100, required=False)
    business_field = forms.CharField(label=_('حوزهٔ فعالیت'), max_length=150, required=False)
    # Optional on the wire: a post without it (an old cached form) means Iran.
    country = forms.ChoiceField(label=_('کشور'), initial=IRAN, required=False,
                                choices=[(c, c) for c in COUNTRIES])
    province = forms.ChoiceField(label=_('استان'), required=False,
                                 choices=[('', _('انتخاب کنید'))] + [(p, p) for p in PROVINCES])
    # A select for Iran (filled from the province), a text box abroad — the
    # browser swaps them, the server checks whichever one applies.
    city = forms.CharField(label=_('شهر'), max_length=64, required=False)
    goals = forms.MultipleChoiceField(
        label=_('هدف اصلی شما'), choices=Lead.Goal.choices,
        widget=forms.CheckboxSelectMultiple, required=False)
    timeline = forms.ChoiceField(
        label=_('زمان احتمالی تصمیم‌گیری یا شروع پروژه'), choices=Lead.Timeline.choices,
        widget=forms.RadioSelect, required=False)
    contact_method = forms.ChoiceField(
        label=_('روش تماس ترجیحی'), choices=Request.ContactMethod.choices,
        widget=forms.RadioSelect, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['full_name'].widget.attrs.update({
            'autocomplete': 'name', 'autofocus': 'autofocus'})
        self.fields['mobile'].widget.attrs.update({
            'inputmode': 'tel', 'autocomplete': 'tel', 'placeholder': '09123456789'})

    def clean_mobile(self):
        mobile = _normalise_mobile(self.cleaned_data.get('mobile', ''))
        if not MOBILE_RE.match(mobile):
            raise forms.ValidationError(_('شمارهٔ موبایل معتبر نیست. نمونه: 09123456789'))
        return mobile

    def clean(self):
        cleaned = super().clean()
        country = cleaned['country'] = cleaned.get('country') or IRAN
        city = (cleaned.get('city') or '').strip()
        if country == IRAN:
            province = cleaned.get('province')
            if not province:
                self.add_error('province', _('استان را انتخاب کنید.'))
            elif city not in CITIES.get(province, []):
                self.add_error('city', _('شهر را از فهرست انتخاب کنید.'))
        else:
            cleaned['province'] = ''
            if not city:
                self.add_error('city', _('نام شهر را وارد کنید.'))
        cleaned['city'] = city
        return cleaned


class LeadStageTwoForm(forms.Form):
    """Project detail. Everything optional; the map pin carries most of the value."""

    latitude = forms.DecimalField(widget=forms.HiddenInput)
    longitude = forms.DecimalField(widget=forms.HiddenInput)
    install_address = forms.CharField(required=False, widget=forms.HiddenInput)
    install_location = forms.ChoiceField(
        label=_('نوع محل نصب'), choices=Request.InstallLocation.choices,
        widget=forms.RadioSelect)
    install_location_note = forms.CharField(
        label=_('توضیح محل نصب'), max_length=200, required=False)
    area_range = forms.ChoiceField(
        label=_('مساحت تقریبی'), choices=Request.AreaRange.choices,
        widget=forms.RadioSelect)
    area_note = forms.CharField(label=_('مساحت دقیق‌تر'), max_length=120, required=False)
    demand_power = forms.ChoiceField(
        label=_('توان مورد تقاضا چقدر است؟'), choices=Lead.DemandPower.choices,
        widget=forms.RadioSelect, required=False)
    shade_status = forms.ChoiceField(
        label=_('سایه‌اندازی'), choices=Request.ShadeStatus.choices,
        widget=forms.RadioSelect)
    shading_note = forms.CharField(
        label=_('موانع موجود'), required=False, widget=forms.Textarea(attrs={'rows': 2}))
    bill_id = forms.CharField(label=_('شناسهٔ قبض برق'), max_length=64, required=False)
    bill_file = forms.FileField(label=_('فایل قبض'), required=False)

    def clean(self):
        cleaned = super().clean()
        if not (cleaned.get('latitude') and cleaned.get('longitude')):
            # The pin is the single most useful answer on this page, and a
            # hidden field cannot show its own error.
            self.add_error(None, _('لطفاً محل پروژه را روی نقشه مشخص کنید.'))
        # A note only means something next to the answer that prompted it.
        if cleaned.get('shade_status') != Request.ShadeStatus.YES:
            cleaned['shading_note'] = ''
        if cleaned.get('install_location') != Request.InstallLocation.OTHER:
            cleaned['install_location_note'] = ''
        return cleaned

    def clean_bill_file(self):
        upload = self.cleaned_data.get('bill_file')
        if not upload:
            return upload
        if not (upload.name or '').lower().endswith(BILL_EXTENSIONS):
            raise forms.ValidationError(_('فقط فایل PDF، تصویر یا ZIP پذیرفته می‌شود.'))
        if upload.size > BILL_MAX_BYTES:
            raise forms.ValidationError(_('حجم فایل نباید بیش از ۱۰ مگابایت باشد.'))
        return upload




class LeadInternalForm(forms.ModelForm):
    """Pars Energy's own read of the lead. Never rendered to the visitor."""

    class Meta:
        model = Lead
        fields = ['temperature', 'next_action', 'marketer_impression',
                  'decision_role', 'notes']
        widgets = {
            'temperature': forms.Select(attrs={'class': 'form-select'}),
            'next_action': forms.TextInput(
                attrs={'class': 'form-control',
                       'placeholder': 'مثلاً: تماس تا پنج‌شنبه برای گرفتن قبض'}),
            'decision_role': forms.TextInput(
                attrs={'class': 'form-control',
                       'placeholder': 'مثلاً: مدیر فنی — تصمیم‌گیر نهایی نیست'}),
            'marketer_impression': forms.Textarea(
                attrs={'rows': 3, 'class': 'form-control',
                       'placeholder': 'چه چیزی واقعاً می‌خواهد؟ چه چیزی نگرانش می‌کند؟'}),
            'notes': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Nothing here is mandatory: a marketer should be able to jot one line
        # at the stand and fill the rest in later, not be blocked by a form.
        for field in self.fields.values():
            field.required = False
