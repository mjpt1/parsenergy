from django import forms
from django.utils.translation import gettext_lazy as _

from .iran_locations import PROVINCES
from .models import (
    ContractSettings,
    ContractTemplate,
    Request,
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
    """The full solar-plant evaluation form (mirrors the pars-energy.com wizard).

    Rendered as a 3-step wizard in the template; all fields POST together.
    """

    needs_financial_consult = forms.TypedChoiceField(
        label=_('آیا نیازی به مشاورهٔ مالی دارید؟'),
        choices=_YESNO, coerce=_coerce_bool, widget=forms.RadioSelect, initial='False',
    )
    has_shading = forms.TypedChoiceField(
        label=_('آیا در محل سایه یا مانعی وجود دارد؟'),
        choices=_YESNO, coerce=_coerce_bool, widget=forms.RadioSelect, initial='False',
    )
    national_id = forms.CharField(
        label=_('کد ملی'), min_length=10, max_length=10,
        widget=forms.TextInput(attrs={'inputmode': 'numeric', 'maxlength': '10'}),
    )
    accepted_terms = forms.BooleanField(
        label=_('قوانین و مقررات را مطالعه کرده و می‌پذیرم.'), required=True,
    )

    class Meta:
        model = Request
        fields = [
            'user_type', 'full_name', 'project_type', 'needs_financial_consult',
            'province', 'city', 'install_address', 'area_m2',
            'install_location', 'building_type', 'has_shading', 'description',
            'ownership_type', 'grid_distance_m', 'storage_interest', 'bill_id',
            'mobile', 'accepted_terms',
        ]
        widgets = {
            'user_type': forms.RadioSelect,
            'project_type': forms.Select,
            'province': forms.Select,
            'city': forms.Select,
            'install_location': forms.RadioSelect,
            'building_type': forms.Select,
            'ownership_type': forms.RadioSelect,
            'storage_interest': forms.RadioSelect,
            'description': forms.Textarea(attrs={'rows': 3}),
            'area_m2': forms.NumberInput(attrs={'min': 1}),
            'grid_distance_m': forms.NumberInput(attrs={'min': 0}),
        }
        labels = {
            'user_type': _('نوع کاربر'),
            'full_name': _('نام شخصیت حقیقی / حقوقی'),
            'project_type': _('نوع پروژه'),
            'province': _('استان'),
            'city': _('شهر'),
            'install_address': _('آدرس محل نصب'),
            'area_m2': _('مساحت تقریبی فضای نصب (متر مربع)'),
            'install_location': _('مشخصات محل نصب'),
            'building_type': _('نوع ساختمان'),
            'description': _('توضیحات'),
            'ownership_type': _('نوع مالکیت محل نصب'),
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
            label=_('شهر'), widget=forms.Select(attrs={'class': 'form-select'}))
        self.fields['project_type'].choices = empty + list(Request.ProjectType.choices)
        self.fields['building_type'].choices = empty + list(Request.BuildingType.choices)
        # Required tuning to match the production form.
        for name in ('project_type', 'area_m2', 'install_location', 'building_type',
                     'ownership_type', 'grid_distance_m', 'storage_interest', 'bill_id', 'mobile'):
            self.fields[name].required = True
        self.fields['install_address'].required = False
        self._style_fields()

    def clean_city(self):
        return (self.cleaned_data.get('city') or '').strip()

    def clean_bill_id(self):
        value = (self.cleaned_data.get('bill_id') or '').strip()
        if value and (not value.isdigit() or len(value) != 13):
            raise forms.ValidationError(_('شناسهٔ قبض باید ۱۳ رقم باشد.'))
        return value

    def clean_national_id(self):
        value = (self.cleaned_data.get('national_id') or '').strip()
        if not (value.isdigit() and len(value) == 10):
            raise forms.ValidationError(_('کد ملی باید ۱۰ رقم باشد.'))
        return value


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
    """Customer opens a new ticket (subject + first message)."""

    subject = forms.CharField(max_length=255, label=_('موضوع'))
    priority = forms.ChoiceField(
        choices=Ticket.Priority.choices,
        initial=Ticket.Priority.NORMAL,
        label=_('اولویت'),
    )
    message = forms.CharField(widget=forms.Textarea(attrs={'rows': 5}), label=_('پیام'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class TicketReplyForm(_BootstrapMixin, forms.Form):
    """A reply within a ticket thread (customer or admin)."""

    body = forms.CharField(widget=forms.Textarea(attrs={'rows': 4}), label=_('پاسخ'))
    attachment = forms.FileField(required=False, label=_('پیوست'))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class ProfileCompletionForm(_BootstrapMixin, forms.ModelForm):
    """Extended profile collected after payment (rule 9)."""

    class Meta:
        model = UserProfileCompletion
        fields = ['national_id', 'address', 'postal_code', 'company_name', 'economic_code']
        widgets = {'address': forms.Textarea(attrs={'rows': 2})}
        labels = {
            'national_id': 'کد ملی',
            'address': 'آدرس',
            'postal_code': 'کد پستی',
            'company_name': 'نام شرکت',
            'economic_code': 'کد اقتصادی',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
