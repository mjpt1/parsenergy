import re

from django import forms
from django.utils.translation import gettext_lazy as _

from .iran_locations import PROVINCES
from .models import (
    ContractorAssignment,
    ContractorProfile,
    ContractSettings,
    ProjectEquipment,
    ProjectInsurance,
    ContractTemplate,
    Request,
    RequestFormField,
    Ticket,
    UserProfileCompletion,
)

_YESNO = [('True', _('بله')), ('False', _('خیر'))]


def _coerce_bool(value):
    return value in ('True', 'true', '1', True)


class _BootstrapMixin:
    """Apply the same Bootstrap widget classes the rest of the panel uses."""

    def _style_fields(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.RadioSelect, forms.CheckboxSelectMultiple)):
                continue  # rendered as a group; styled in the template
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')


class RequestSubmitForm(_BootstrapMixin, forms.ModelForm):
    """Smart multi-step solar evaluation form (conditional wizard).

    Branching is driven by `request_type` (اختصاصی / مشارکتی / مشاوره) and, for
    partnership, by `partnership_type` (سرمایه‌گذاری / فضای نصب). Rendered as a
    6-step conditional wizard; all fields POST together and per-path
    requirements are enforced in clean().
    """

    request_type = forms.ChoiceField(
        label=_('چه نوع درخواستی دارید؟'),
        choices=Request.RequestType.choices, widget=forms.RadioSelect,
    )
    partnership_type = forms.ChoiceField(
        label=_('نوع مشارکت شما'), required=False,
        choices=Request.PartnershipType.choices, widget=forms.RadioSelect,
    )
    investment_range = forms.ChoiceField(
        label=_('میزان سرمایهٔ مدنظر شما'), required=False,
        choices=Request.InvestmentRange.choices, widget=forms.RadioSelect,
    )
    area_range = forms.ChoiceField(
        label=_('مساحت تقریبی فضای نصب'), required=False,
        choices=Request.AreaRange.choices, widget=forms.RadioSelect,
    )
    shade_status = forms.ChoiceField(
        label=_('آیا محل نصب سایه یا مانعی دارد؟'), required=False,
        choices=Request.ShadeStatus.choices, widget=forms.RadioSelect,
    )
    contact_method = forms.ChoiceField(
        label=_('روش تماس ترجیحی شما'),
        choices=Request.ContactMethod.choices, widget=forms.RadioSelect,
        initial=Request.ContactMethod.CALL,
    )
    needs_financial_consult = forms.TypedChoiceField(
        label=_('آیا نیازی به مشاورهٔ مالی دارید؟'),
        choices=_YESNO, coerce=_coerce_bool, widget=forms.RadioSelect, initial='False',
        required=False,
    )
    latitude = forms.DecimalField(required=False, widget=forms.HiddenInput())
    longitude = forms.DecimalField(required=False, widget=forms.HiddenInput())
    accepted_terms = forms.BooleanField(
        label=_('قوانین و مقررات را مطالعه کرده و می‌پذیرم.'), required=True,
    )

    how_heard = forms.ChoiceField(
        label=_('چگونه با پارس انرژی آشنا شدید؟'),
        choices=[('', _('انتخاب کنید'))] + list(Request.HowHeard.choices),
        required=False,
    )
    # Attribution capture (filled from query/session; hidden on the form)
    utm_source = forms.CharField(required=False, widget=forms.HiddenInput())
    utm_medium = forms.CharField(required=False, widget=forms.HiddenInput())
    utm_campaign = forms.CharField(required=False, widget=forms.HiddenInput())
    utm_content = forms.CharField(required=False, widget=forms.HiddenInput())
    utm_term = forms.CharField(required=False, widget=forms.HiddenInput())
    campaign_name = forms.CharField(required=False, widget=forms.HiddenInput())
    medium = forms.CharField(required=False, widget=forms.HiddenInput())
    landing_page = forms.CharField(required=False, widget=forms.HiddenInput())
    referrer = forms.CharField(required=False, widget=forms.HiddenInput())
    device_type = forms.CharField(required=False, widget=forms.HiddenInput())
    first_visit_at = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Request
        fields = [
            'request_type', 'user_type', 'full_name',
            'province', 'city', 'install_address',
            'partnership_type', 'investment_range',
            'install_location', 'area_range', 'shade_status', 'building_type',
            'needs_financial_consult', 'grid_distance_m', 'storage_interest', 'bill_id',
            'description', 'contact_method', 'how_heard',
            'latitude', 'longitude', 'mobile', 'accepted_terms',
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term',
            'campaign_name', 'medium', 'landing_page', 'referrer',
            'device_type', 'first_visit_at',
        ]
        widgets = {
            'user_type': forms.RadioSelect,
            'province': forms.Select,
            'install_location': forms.RadioSelect,
            'building_type': forms.Select,
            'storage_interest': forms.RadioSelect,
            'description': forms.Textarea(attrs={'rows': 3}),
            'grid_distance_m': forms.NumberInput(attrs={'min': 0}),
        }
        labels = {
            'user_type': _('نوع کاربر'),
            'full_name': _('نام شخصیت حقیقی / حقوقی'),
            'province': _('استان'),
            'city': _('شهر'),
            'install_address': _('آدرس محل نصب'),
            'install_location': _('مشخصات محل نصب'),
            'building_type': _('نوع ساختمان'),
            'description': _('توضیحات تکمیلی'),
            'grid_distance_m': _('فاصله تا شبکهٔ سراسری (متر)'),
            'storage_interest': _('تمایل به سیستم ذخیره‌سازی؟'),
            'bill_id': _('شناسهٔ قبض برق (۱۳ رقمی)'),
            'mobile': _('شماره موبایل'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        empty = [('', _('انتخاب کنید'))]
        self.fields['province'].choices = empty + [(p, p) for p in PROVINCES]
        # City options are filled client-side from the chosen province; accept any.
        self.fields['city'] = forms.CharField(
            label=_('شهر'), required=False,
            widget=forms.Select(attrs={'class': 'form-select'}))
        self.fields['building_type'].choices = empty + list(Request.BuildingType.choices)
        # Conditional fields: optional at field level, enforced per-path in clean().
        for name in ('partnership_type', 'investment_range', 'area_range',
                     'shade_status', 'building_type', 'grid_distance_m',
                     'storage_interest', 'bill_id', 'install_location',
                     'needs_financial_consult', 'install_address'):
            self.fields[name].required = False
        self.fields['full_name'].required = True
        self.fields['mobile'].required = True
        self._add_custom_fields()
        self._style_fields()

    def _add_custom_fields(self):
        """Layer in fields an admin added through the form builder (RequestFormField
        with is_system=False). Their values end up in Request.custom_fields — the
        ~30 system fields above keep using their real columns, untouched."""
        self.custom_field_keys = []
        for f in RequestFormField.objects.filter(is_system=False, is_active=True):
            if f.key in self.fields:
                continue  # a custom field can't shadow a system field's key
            choices = [(c.get('value', ''), c.get('label', '')) for c in (f.choices or [])]
            if f.field_type == RequestFormField.TEXTAREA:
                field = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}))
            elif f.field_type == RequestFormField.NUMBER:
                field = forms.IntegerField()
            elif f.field_type == RequestFormField.SELECT:
                field = forms.ChoiceField(choices=[('', _('انتخاب کنید'))] + choices)
            elif f.field_type == RequestFormField.RADIO:
                field = forms.ChoiceField(choices=choices, widget=forms.RadioSelect)
            elif f.field_type == RequestFormField.YESNO:
                field = forms.TypedChoiceField(
                    choices=_YESNO, coerce=_coerce_bool, widget=forms.RadioSelect, initial='False')
            elif f.field_type == RequestFormField.DATE:
                from apps.core.dates import JalaliDateField
                field = JalaliDateField()
            else:
                field = forms.CharField()
            field.label = f.label
            field.help_text = f.help_text
            field.required = f.required
            self.fields[f.key] = field
            self.custom_field_keys.append(f.key)

    def clean_city(self):
        return (self.cleaned_data.get('city') or '').strip()

    def clean_bill_id(self):
        value = (self.cleaned_data.get('bill_id') or '').strip()
        if value and (not value.isdigit() or len(value) != 13):
            raise forms.ValidationError(_('شناسهٔ قبض باید ۱۳ رقم باشد.'))
        return value

    def clean(self):
        cd = super().clean()
        rtype = cd.get('request_type')

        def require(field, msg):
            if not cd.get(field):
                self.add_error(field, msg)

        if rtype == Request.RequestType.DEDICATED:
            require('install_location', _('محل نصب را انتخاب کنید.'))
            require('area_range', _('بازهٔ مساحت را انتخاب کنید.'))
            require('shade_status', _('وضعیت سایه را مشخص کنید.'))
        elif rtype == Request.RequestType.PARTNERSHIP:
            ptype = cd.get('partnership_type')
            require('partnership_type', _('نوع مشارکت را انتخاب کنید.'))
            if ptype == Request.PartnershipType.INVESTMENT:
                require('investment_range', _('میزان سرمایه را انتخاب کنید.'))
            elif ptype == Request.PartnershipType.SPACE:
                require('install_location', _('محل نصب را انتخاب کنید.'))
                require('area_range', _('بازهٔ مساحت را انتخاب کنید.'))
        # CONSULTATION: only contact details are required (no technical fields).
        return cd


class ContractTemplateForm(_BootstrapMixin, forms.ModelForm):
    """Create/edit a named contract template. The body can be typed directly or
    loaded from an uploaded .txt or .docx (Word) file."""

    upload = forms.FileField(required=False, label=_('بارگذاری فایل (.txt یا .docx)'))

    class Meta:
        model = ContractTemplate
        fields = ['name', 'body', 'is_active']
        widgets = {'body': forms.Textarea(attrs={'rows': 16})}
        labels = {
            'name': _('نام قالب'),
            'body': _('متن قالب'),
            'is_active': _('قالب فعال'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class ContractSettingsForm(_BootstrapMixin, forms.ModelForm):
    """Company header, signature, page margins and customer-page texts."""

    class Meta:
        model = ContractSettings
        fields = [
            'company_name', 'company_address', 'company_phone', 'logo',
            'header_note', 'footer_note', 'signature_text',
            'margin_top', 'margin_right', 'margin_bottom', 'margin_left',
            'customer_page_title', 'customer_page_intro',
        ]
        widgets = {
            'company_address': forms.Textarea(attrs={'rows': 2}),
            'header_note': forms.Textarea(attrs={'rows': 2}),
            'footer_note': forms.Textarea(attrs={'rows': 2}),
            'customer_page_intro': forms.Textarea(attrs={'rows': 2}),
        }
        labels = {
            'company_name': _('نام شرکت'),
            'company_address': _('آدرس شرکت'),
            'company_phone': _('تلفن شرکت'),
            'logo': _('لوگو'),
            'header_note': _('متن سربرگ'),
            'footer_note': _('متن پاورقی'),
            'signature_text': _('متن امضا'),
            'margin_top': _('حاشیه بالا (میلی‌متر)'),
            'margin_right': _('حاشیه راست (میلی‌متر)'),
            'margin_bottom': _('حاشیه پایین (میلی‌متر)'),
            'margin_left': _('حاشیه چپ (میلی‌متر)'),
            'customer_page_title': _('عنوان صفحهٔ مشتری'),
            'customer_page_intro': _('توضیح صفحهٔ مشتری'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class TicketForm(_BootstrapMixin, forms.Form):
    """Open a ticket to a department (owner/customer or internal staff)."""

    department = forms.ChoiceField(
        choices=Ticket.Department.choices,
        initial=Ticket.Department.SALES,
        label=_('این تیکت برای کدام بخش است؟'),
    )
    subject = forms.CharField(max_length=255, label=_('موضوع'))
    priority = forms.ChoiceField(
        choices=Ticket.Priority.choices,
        initial=Ticket.Priority.NORMAL,
        label=_('اولویت'),
    )
    message = forms.CharField(widget=forms.Textarea(attrs={'rows': 5}), label=_('پیام'))

    def __init__(self, *args, exclude_departments=None, **kwargs):
        super().__init__(*args, **kwargs)
        if exclude_departments:
            skip = set(exclude_departments)
            self.fields['department'].choices = [
                c for c in Ticket.Department.choices if c[0] not in skip
            ]
        self._style_fields()


class TicketReplyForm(_BootstrapMixin, forms.Form):
    """A reply within a ticket thread (customer or admin)."""

    body = forms.CharField(widget=forms.Textarea(attrs={'rows': 4}), label=_('پاسخ'))
    attachment = forms.FileField(required=False, label=_('پیوست'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class _MoneyField(forms.CharField):
    def to_python(self, value):
        from decimal import Decimal, InvalidOperation

        from apps.core.dates import latin_digits
        text = re.sub(r'[,،٬\s\u200c]', '', latin_digits(value))
        if text in self.empty_values:
            return None
        try:
            amount = Decimal(text)
        except InvalidOperation:
            raise forms.ValidationError(_('مبلغ معتبر نیست.'))
        if amount <= 0 or amount != amount.to_integral_value():
            raise forms.ValidationError(_('مبلغ باید عدد صحیح و بیشتر از صفر باشد.'))
        return amount


class ProjectContractForm(_BootstrapMixin, forms.Form):
    MAIN = ('contract_number', 'signed_on', 'total_amount', 'file', 'description')
    TITLES = {1: _('پیش‌پرداخت'), 2: _('پرداخت میانی'), 3: _('تسویهٔ نهایی')}

    contract_number = forms.CharField(label=_('شمارهٔ قرارداد'), max_length=64)
    total_amount = _MoneyField(label=_('مبلغ کل (تومان)'), widget=forms.TextInput(
        attrs={'inputmode': 'numeric', 'data-money': '1'}))
    file = forms.FileField(label=_('فایل قرارداد امضاشده'), required=False,
                           help_text=_('PDF، تصویر یا Word تا ۲۰ مگابایت'))
    description = forms.CharField(label=_('توضیحات'), required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, contract=None, **kwargs):
        from apps.core.dates import JalaliDateField
        super().__init__(*args, **kwargs)
        self.fields['signed_on'] = JalaliDateField(label=_('تاریخ امضا'))
        rows = {i.number: i for i in contract.installments.all()} if contract else {}
        for number in (1, 2, 3):
            row = rows.get(number)
            self.fields[f'title_{number}'] = forms.CharField(
                max_length=120, initial=row.title if row else self.TITLES[number])
            self.fields[f'amount_{number}'] = _MoneyField(
                initial=f'{row.amount:.0f}' if row else '',
                widget=forms.TextInput(attrs={'inputmode': 'numeric', 'data-money': '1'}))
            self.fields[f'due_{number}'] = JalaliDateField(initial=row.due_date if row else None)
        if contract:
            for name in ('contract_number', 'signed_on', 'description'):
                self.fields[name].initial = getattr(contract, name)
            self.fields['total_amount'].initial = f'{contract.total_amount:.0f}'
        self._style_fields()

    def main_fields(self):
        return [self[name] for name in self.MAIN]

    def clean_file(self):
        upload = self.cleaned_data.get('file')
        if upload:
            from .services import project
            try:
                project.check_upload(upload, allowed=project.CONTRACT_TYPES)
            except project.ProjectError as exc:
                raise forms.ValidationError(str(exc))
        return upload

    def clean(self):
        data = super().clean()
        amounts = [data.get(f'amount_{n}') for n in (1, 2, 3)]
        if all(amounts) and data.get('total_amount') and sum(amounts) != data['total_amount']:
            self.add_error('total_amount', _('جمع سه قسط باید با مبلغ کل برابر باشد.'))
        dues = [data.get(f'due_{n}') for n in (1, 2, 3)]
        if all(dues) and not dues[0] <= dues[1] <= dues[2]:
            self.add_error('due_3', _('موعد قسط‌ها باید به ترتیب باشد.'))
        return data


def _jalali_field(label, required=False):
    from apps.core.dates import JalaliDateField
    return JalaliDateField(label=label, required=required)


class ProjectEquipmentForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ProjectEquipment
        fields = ['category', 'name', 'model_name', 'serial_number', 'quantity', 'unit', 'supplier',
                  'purchased_on', 'warranty_until', 'note', 'visible_to_customer']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['purchased_on'] = _jalali_field(_('تاریخ خرید'))
        self.fields['warranty_until'] = _jalali_field(_('پایان گارانتی'))
        self.order_fields(self.Meta.fields)
        self._style_fields()

    def clean_quantity(self):
        value = self.cleaned_data['quantity']
        if value <= 0:
            raise forms.ValidationError(_('تعداد باید بیشتر از صفر باشد.'))
        return value


class ProjectInsuranceForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ProjectInsurance
        fields = ['phase', 'kind', 'insurer', 'policy_number', 'start_date', 'end_date', 'coverage_amount',
                  'file', 'note', 'visible_to_customer']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['start_date'] = _jalali_field(_('شروع اعتبار'), True)
        self.fields['end_date'] = _jalali_field(_('پایان اعتبار'), True)
        self.fields['coverage_amount'] = _MoneyField(
            label=_('سرمایهٔ بیمه (تومان)'), required=False, initial=(
                f'{self.instance.coverage_amount:.0f}' if self.instance.coverage_amount else ''),
            widget=forms.TextInput(attrs={'inputmode': 'numeric', 'data-money': '1'}))
        self.fields['file'].widget = forms.FileInput()
        self.order_fields(self.Meta.fields)
        self._style_fields()

    def clean_file(self):
        upload = self.cleaned_data.get('file')
        if upload and upload is not self.instance.file and hasattr(upload, 'content_type'):
            from .services import project
            try:
                project.check_upload(upload, allowed=project.RECEIPT_TYPES)
            except project.ProjectError as exc:
                raise forms.ValidationError(str(exc))
        return upload

    def clean(self):
        data = super().clean()
        if data.get('start_date') and data.get('end_date') and data['end_date'] < data['start_date']:
            self.add_error('end_date', _('پایان اعتبار نمی‌تواند قبل از شروع باشد.'))
        return data


class ContractorAssignmentForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ContractorAssignment
        fields = ['contractor', 'scope', 'start_date', 'end_date', 'share_contact']

    def __init__(self, *args, can_share_contact=False, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth import get_user_model
        User = get_user_model()
        field = self.fields['contractor']
        field.label = _('پیمانکار')
        field.queryset = User.objects.filter(role=User.Role.CONTRACTOR, is_active=True).order_by('first_name', 'username')
        field.label_from_instance = lambda u: u.get_full_name() or u.username
        self.fields['start_date'] = _jalali_field(_('تاریخ شروع'))
        self.fields['end_date'] = _jalali_field(_('تاریخ پایان'))
        if not can_share_contact:
            self.fields.pop('share_contact')
        self.order_fields(self.Meta.fields)
        self._style_fields()


class ContractorProfileForm(_BootstrapMixin, forms.ModelForm):
    class Meta:
        model = ContractorProfile
        fields = ['company_name', 'expertise', 'license_no', 'city', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class LeadForm(_BootstrapMixin, forms.ModelForm):
    """A lead typed in or corrected by staff."""

    class Meta:
        model = Request
        fields = ['full_name', 'mobile', 'user_type', 'province', 'city', 'install_address',
                  'request_type', 'install_location', 'area_range', 'bill_id', 'how_heard',
                  'priority', 'description']
        labels = {
            'full_name': _('نام شخص یا شرکت'), 'mobile': _('شماره موبایل'), 'user_type': _('نوع مشتری'),
            'province': _('استان'), 'city': _('شهر'), 'install_address': _('آدرس محل نصب'),
            'request_type': _('نوع درخواست'), 'install_location': _('محل نصب'), 'area_range': _('مساحت تقریبی'),
            'bill_id': _('شناسهٔ قبض برق'), 'how_heard': _('منبع لید'), 'priority': _('اولویت'),
            'description': _('توضیحات'),
        }
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        province = self.instance.province if self.instance.pk else ''
        names = list(PROVINCES) + ([province] if province and province not in PROVINCES else [])
        self.fields['province'] = forms.ChoiceField(
            label=_('استان'), choices=[('', _('انتخاب کنید'))] + [(p, p) for p in names],
            widget=forms.Select(attrs={'data-loc': 'province'}))
        city = (self.data.get('city') if self.is_bound else self.instance.city) or ''
        self.fields['city'].widget = forms.Select(attrs={'data-loc': 'city', 'data-selected': city})
        self.fields['mobile'].widget.attrs.update({'inputmode': 'numeric', 'dir': 'ltr'})
        self.fields['bill_id'].widget.attrs.update({'inputmode': 'numeric', 'dir': 'ltr'})
        if self.instance.pk and (self.instance.user_id or self.instance.identity_verified):
            # The number is this customer's sign-in and identity link.
            self.fields['mobile'].disabled = True
            self.fields['mobile'].help_text = _('موبایل پرونده‌ای که به حساب مشتری وصل یا احراز شده قابل تغییر نیست.')
        self._style_fields()

    def clean_mobile(self):
        from apps.core.dates import latin_digits
        value = latin_digits(self.cleaned_data.get('mobile'))
        if not re.fullmatch(r'09\d{9}', value):
            raise forms.ValidationError(_('شماره موبایل باید ۱۱ رقم و با ۰۹ شروع شود.'))
        return value

    def clean_bill_id(self):
        from apps.core.dates import latin_digits
        value = latin_digits(self.cleaned_data.get('bill_id'))
        if value and not re.fullmatch(r'\d{13}', value):
            raise forms.ValidationError(_('شناسهٔ قبض باید ۱۳ رقم باشد.'))
        return value


class ProfileCompletionForm(_BootstrapMixin, forms.ModelForm):
    """The customer's editable profile (also used to complete profile post-payment)."""

    class Meta:
        model = UserProfileCompletion
        fields = [
            'full_name', 'mobile', 'national_id', 'province', 'city',
            'address', 'postal_code', 'company_name', 'economic_code',
        ]
        widgets = {
            'address': forms.Textarea(attrs={'rows': 2}),
            'province': forms.Select,
        }
        labels = {
            'full_name': 'نام و نام خانوادگی',
            'mobile': 'شماره موبایل',
            'national_id': 'کد ملی / شناسهٔ ملی شرکت',
            'province': 'استان',
            'city': 'شهر',
            'address': 'آدرس',
            'postal_code': 'کد پستی',
            'company_name': 'نام شرکت (اختیاری)',
            'economic_code': 'کد اقتصادی (اختیاری)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['province'] = forms.ChoiceField(
            label='استان', required=False,
            choices=[('', 'انتخاب کنید')] + [(p, p) for p in PROVINCES],
            widget=forms.Select(attrs={'data-loc': 'province'}))
        # The city list follows the province in the browser (location-select.js);
        # the saved value rides along in data-selected so it survives a reload.
        current_city = (self.data.get('city') if self.is_bound
                        else getattr(self.instance, 'city', '')) or ''
        self.fields['city'].widget = forms.Select(
            attrs={'data-loc': 'city', 'data-selected': current_city})
        self.fields['mobile'].widget.attrs.setdefault('inputmode', 'numeric')
        for name in self.fields:
            self.fields[name].required = name in ('full_name', 'mobile')
        self._style_fields()

    def clean_national_id(self):
        from apps.core.dates import latin_digits
        value = latin_digits(self.cleaned_data.get('national_id'))
        if value and not (value.isdigit() and len(value) in (10, 11)):
            raise forms.ValidationError(_('کد ملی ۱۰ رقم و شناسهٔ ملی شرکت ۱۱ رقم است.'))
        return value


class RequestEditForm(RequestSubmitForm):
    """Customer edits an existing request through the *same* conditional wizard,
    minus identity verification (mobile/national_id are fixed once verified) and
    the terms checkbox (already accepted). Lets a "needs consultation" user go
    back and refine the same multi-step form instead of refilling it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Drop identity / OTP / terms — editing must not re-verify or re-collect them.
        for name in ('national_id', 'mobile', 'accepted_terms'):
            self.fields.pop(name, None)
        # Attribution belongs to the first visit. Left on the form, the empty
        # hidden inputs overwrote it on every edit, and an empty first_visit_at
        # could not be saved at all (HTTP 500 on /requests/mine/<id>/edit/).
        for name in self.ATTRIBUTION_FIELDS:
            self.fields.pop(name, None)

    ATTRIBUTION_FIELDS = (
        'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term',
        'campaign_name', 'medium', 'landing_page', 'referrer',
        'device_type', 'first_visit_at',
    )

    def save(self, commit=True):
        obj = super().save(commit=False)
        # Keep the legacy boolean mirror in sync with the new shade choice.
        obj.has_shading = self.cleaned_data.get('shade_status') == Request.ShadeStatus.YES
        if commit:
            obj.save()
        return obj
