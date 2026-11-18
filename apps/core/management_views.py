from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, FormView
from django.urls import reverse_lazy
from django.contrib import messages
from .services import write_audit_log
from django.utils.translation import gettext_lazy as _
from .models import SettingChangeRequest, SystemParameter, SecuritySetting, APIConnection, ProtocolAdapter, DatabaseBackup, AuditLog, ServerHealthMetric
from django import forms


class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        request = getattr(self, 'request', None)
        user = getattr(request, 'user', None)
        return bool(user and (user.is_superuser or user.has_permission_code('admin.access')))


SENSITIVE_WORDS = ('key', 'secret', 'token', 'password')
KEEP_CURRENT = _('برای حفظ مقدار فعلی خالی بگذارید')


# Changing these affects customers' messages, identity checks and money, so a
# technical user's change waits for an administrator.
APPROVAL_PREFIXES = ('sms_', 'shahkar_', 'payment_')


def needs_approval(key):
    return key.strip().lower().startswith(APPROVAL_PREFIXES)


def is_sensitive_parameter(param):
    return param.is_secret or any(word in param.key.lower() for word in SENSITIVE_WORDS)


def make_write_only(form, name):
    """A stored secret can be replaced from this form but never read back."""
    field = form.fields[name]
    attrs = {**field.widget.attrs, 'autocomplete': 'new-password', 'placeholder': KEEP_CURRENT}
    attrs.pop('value', None)
    field.widget = forms.PasswordInput(render_value=False, attrs=attrs)
    field.required = False


class TechnicalSettingsMixin(AdminRequiredMixin):
    """Settings the technical team also runs. They may change stored keys and
    passwords, but only administrators can read them back."""

    def test_func(self):
        return super().test_func() or getattr(self.request.user, 'role', '') == 'technical'

    @property
    def hides_secrets(self):
        return not AdminRequiredMixin.test_func(self)


class SystemParameterForm(forms.ModelForm):
    restricted = False   # set for users whose service changes need approval

    class Meta:
        model = SystemParameter
        fields = '__all__'

    def clean_key(self):
        key = self.cleaned_data['key']
        if self.restricted and needs_approval(key):
            raise forms.ValidationError(_('پیامک، شاهکار و درگاه پرداخت را از «تنظیمات سرویس‌ها» تغییر دهید تا مدیر تأیید کند.'))
        return key


class SecuritySettingForm(forms.ModelForm):
    class Meta:
        model = SecuritySetting
        fields = '__all__'


class APIConnectionForm(forms.ModelForm):
    class Meta:
        model = APIConnection
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == 'is_active':
                field.widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault('class', 'form-select')
            else:
                field.widget.attrs.setdefault('class', 'form-control')


class ProtocolAdapterForm(forms.ModelForm):
    class Meta:
        model = ProtocolAdapter
        fields = '__all__'


class DatabaseBackupForm(forms.ModelForm):
    class Meta:
        model = DatabaseBackup
        fields = '__all__'


class AISettingsForm(forms.Form):
    provider = forms.ChoiceField(
        choices=[
            ('openai-compatible', 'OpenAI-compatible'),
            ('openai', 'OpenAI'),
            ('azure', 'Azure OpenAI'),
            ('gemini', 'Google Gemini'),
            ('claude', 'Anthropic Claude'),
        ],
        required=True,
        label='Provider',
    )
    base_url = forms.URLField(label='Base URL', required=False)
    model = forms.CharField(label='Model', required=False)
    api_key = forms.CharField(label='API Key', required=False, widget=forms.PasswordInput(render_value=True))
    auth_header = forms.CharField(label='Auth Header', required=False, initial='Authorization')
    auth_prefix = forms.CharField(label='Auth Prefix', required=False, initial='Bearer')
    system_prompt = forms.CharField(label='System Prompt', required=False, widget=forms.Textarea(attrs={'rows': 4}))
    enabled = forms.BooleanField(label='فعال', required=False)
    # Iranian OpenAI-compatible gateways — used when the main one fails or
    # international internet is cut.
    gapgpt_key = forms.CharField(label='GapGPT API Key', required=False,
                                 widget=forms.PasswordInput(render_value=True))
    gapgpt_model = forms.CharField(label='GapGPT Model', required=False)
    gapgpt_enabled = forms.BooleanField(label='GapGPT فعال', required=False)
    avalai_key = forms.CharField(label='AvalAI API Key', required=False,
                                 widget=forms.PasswordInput(render_value=True))
    avalai_model = forms.CharField(label='AvalAI Model', required=False)
    avalai_enabled = forms.BooleanField(label='AvalAI فعال', required=False)
    order = forms.ChoiceField(label='اولویت', choices=[
        ('primary', 'اول سرویس اصلی، بعد GapGPT، بعد AvalAI'),
        ('gapgpt', 'اول GapGPT، بعد AvalAI، بعد سرویس اصلی'),
        ('avalai', 'اول AvalAI، بعد GapGPT، بعد سرویس اصلی'),
    ])
    chat_enabled = forms.BooleanField(label='دستیار گفتگو برای مشتریان', required=False)
    chat_per_visitor = forms.IntegerField(label='پیام در ساعت برای هر بازدیدکننده', min_value=0, required=False)
    chat_total = forms.IntegerField(label='کل پیام‌ها در ساعت', min_value=0, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.core import ai_limits
        # One row per AI feature: on/off, allowed roles, daily cap per person.
        for feature, (label, _roles, _daily) in ai_limits.FEATURES.items():
            self.fields[f'feat_{feature}_enabled'] = forms.BooleanField(label=label, required=False)
            self.fields[f'feat_{feature}_roles'] = forms.MultipleChoiceField(
                label=label, required=False, choices=ai_limits.ROLES,
                widget=forms.CheckboxSelectMultiple)
            self.fields[f'feat_{feature}_daily'] = forms.IntegerField(
                label=label, min_value=0, required=False)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxSelectMultiple):
                continue
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault('class', 'form-select')
            else:
                field.widget.attrs.setdefault('class', 'form-control')


class SystemParameterListView(LoginRequiredMixin, TechnicalSettingsMixin, ListView):
    model = SystemParameter
    template_name = 'core/list.html'
    extra_context = {'page_title': _('پارامترهای سیستم'), 'resource_key': 'parameters'}


class SystemParameterCreateView(LoginRequiredMixin, TechnicalSettingsMixin, CreateView):
    model = SystemParameter
    form_class = SystemParameterForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:parameters')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.restricted = self.hides_secrets
        return form


class SystemParameterUpdateView(LoginRequiredMixin, TechnicalSettingsMixin, UpdateView):
    model = SystemParameter
    form_class = SystemParameterForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:parameters')

    def _write_only(self):
        return self.hides_secrets and is_sensitive_parameter(self.object)

    def get_object(self, queryset=None):
        param = super().get_object(queryset)
        if self.hides_secrets and needs_approval(param.key):
            raise PermissionDenied
        return param

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.restricted = self.hides_secrets
        if self._write_only():
            make_write_only(form, 'value')
            form.fields['key'].disabled = True
            form.fields['is_secret'].disabled = True
        return form

    def form_valid(self, form):
        if self._write_only() and not form.cleaned_data.get('value'):
            form.instance.value = SystemParameter.objects.get(pk=self.object.pk).value
        return super().form_valid(form)


class SystemParameterDeleteView(LoginRequiredMixin, TechnicalSettingsMixin, DeleteView):
    model = SystemParameter
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('core:parameters')

    def get_object(self, queryset=None):
        param = super().get_object(queryset)
        if self.hides_secrets and (is_sensitive_parameter(param) or needs_approval(param.key)):
            raise PermissionDenied
        return param


class SecuritySettingListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = SecuritySetting
    template_name = 'core/list.html'
    extra_context = {'page_title': _('تنظیمات امنیتی'), 'resource_key': 'security'}


class SecuritySettingCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = SecuritySetting
    form_class = SecuritySettingForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:security')


class SecuritySettingUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = SecuritySetting
    form_class = SecuritySettingForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:security')


class SecuritySettingDeleteView(LoginRequiredMixin, AdminRequiredMixin, DeleteView):
    model = SecuritySetting
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('core:security')


class APIConnectionListView(LoginRequiredMixin, TechnicalSettingsMixin, ListView):
    model = APIConnection
    template_name = 'core/list.html'
    extra_context = {'page_title': _('اتصالات API'), 'resource_key': 'connections'}


class APIConnectionCreateView(LoginRequiredMixin, TechnicalSettingsMixin, CreateView):
    model = APIConnection
    form_class = APIConnectionForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:connections')


class APIConnectionUpdateView(LoginRequiredMixin, TechnicalSettingsMixin, UpdateView):
    model = APIConnection
    form_class = APIConnectionForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:connections')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if self.hides_secrets:
            make_write_only(form, 'token')
        return form

    def form_valid(self, form):
        if self.hides_secrets and not form.cleaned_data.get('token'):
            form.instance.token = APIConnection.objects.get(pk=self.object.pk).token
        return super().form_valid(form)


class APIConnectionDeleteView(LoginRequiredMixin, TechnicalSettingsMixin, DeleteView):
    model = APIConnection
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('core:connections')


class InverterAPIConnectionView(LoginRequiredMixin, TechnicalSettingsMixin, CreateView):
    model = APIConnection
    form_class = APIConnectionForm
    template_name = 'core/inverter_api.html'
    success_url = reverse_lazy('core:inverter-api')

    def form_valid(self, form):
        messages.success(self.request, _('اتصال API اینورتر با موفقیت ذخیره شد.'))
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = _('ثبت API اینورترها')
        context['connections'] = APIConnection.objects.order_by('-id')[:20]
        return context


class ProtocolAdapterListView(LoginRequiredMixin, TechnicalSettingsMixin, ListView):
    model = ProtocolAdapter
    template_name = 'core/list.html'
    extra_context = {'page_title': _('پروتکل‌ها'), 'resource_key': 'protocols'}


class ProtocolAdapterCreateView(LoginRequiredMixin, TechnicalSettingsMixin, CreateView):
    model = ProtocolAdapter
    form_class = ProtocolAdapterForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:protocols')


class ProtocolAdapterUpdateView(LoginRequiredMixin, TechnicalSettingsMixin, UpdateView):
    model = ProtocolAdapter
    form_class = ProtocolAdapterForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:protocols')


class ProtocolAdapterDeleteView(LoginRequiredMixin, TechnicalSettingsMixin, DeleteView):
    model = ProtocolAdapter
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('core:protocols')


class DatabaseBackupListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = DatabaseBackup
    template_name = 'core/list.html'
    extra_context = {'page_title': _('بکاپ دیتابیس'), 'resource_key': 'backups'}


class DatabaseBackupCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = DatabaseBackup
    form_class = DatabaseBackupForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:backups')


class DatabaseBackupUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = DatabaseBackup
    form_class = DatabaseBackupForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:backups')


class DatabaseBackupDeleteView(LoginRequiredMixin, AdminRequiredMixin, DeleteView):
    model = DatabaseBackup
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('core:backups')


class AuditLogListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = AuditLog
    template_name = 'core/logs.html'
    paginate_by = 25
    extra_context = {'page_title': _('لاگ‌های امنیتی')}


class ServerHealthListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = ServerHealthMetric
    template_name = 'core/health.html'
    paginate_by = 25
    extra_context = {'page_title': _('سلامت سرورها')}


class AISettingsView(LoginRequiredMixin, AdminRequiredMixin, FormView):
    template_name = 'core/ai_settings.html'
    form_class = AISettingsForm
    success_url = reverse_lazy('core:ai-settings')

    def _get_param(self, key, default=''):
        param = SystemParameter.objects.filter(key=key).first()
        return param.value if param else default

    def _set_param(self, key, value, is_secret=False):
        SystemParameter.objects.update_or_create(
            key=key,
            defaults={
                'value': str(value),
                'description': 'AI Settings',
                'is_secret': is_secret,
            },
        )

    def get_initial(self):
        return {
            'provider': self._get_param('ai_provider', 'openai-compatible'),
            'base_url': self._get_param('ai_base_url', 'https://api.openai.com/v1'),
            'model': self._get_param('ai_model', 'gpt-4.1-mini'),
            'api_key': self._get_param('ai_api_key', ''),
            'auth_header': self._get_param('ai_auth_header', 'Authorization'),
            'auth_prefix': self._get_param('ai_auth_prefix', 'Bearer'),
            'system_prompt': self._get_param('ai_system_prompt', ''),
            'enabled': self._get_param('ai_enabled', 'false') == 'true',
            'gapgpt_key': self._get_param('ai_gapgpt_key', ''),
            'gapgpt_model': self._get_param('ai_gapgpt_model', 'gpt-4o-mini'),
            'gapgpt_enabled': self._get_param('ai_gapgpt_enabled', 'true') == 'true',
            'avalai_key': self._get_param('ai_avalai_key', ''),
            'avalai_model': self._get_param('ai_avalai_model', 'gpt-4o-mini'),
            'avalai_enabled': self._get_param('ai_avalai_enabled', 'true') == 'true',
            'order': self._get_param('ai_order', 'primary'),
            'chat_enabled': self._get_param('ai_chat_enabled', 'true') == 'true',
            **self._limit_initial(),
        }

    def _limit_initial(self):
        from apps.core import ai_limits
        data = {}
        for feature in ai_limits.FEATURES:
            cfg = ai_limits.settings_for(feature)
            data[f'feat_{feature}_enabled'] = cfg['enabled']
            data[f'feat_{feature}_roles'] = cfg['roles']
            data[f'feat_{feature}_daily'] = cfg['daily']
        data['chat_per_visitor'], data['chat_total'] = ai_limits.chat_limits()
        return data

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.core import ai
        ctx['active_providers'] = [p.label for p in ai.providers()]
        from apps.core import ai_limits
        form = ctx['form']
        ctx['feature_rows'] = [
            {'label': label, 'enabled': form[f'feat_{f}_enabled'],
             'roles': form[f'feat_{f}_roles'], 'daily': form[f'feat_{f}_daily']}
            for f, (label, _r, _d) in ai_limits.FEATURES.items()
        ]
        return ctx

    def form_valid(self, form):
        cleaned = form.cleaned_data
        self._set_param('ai_provider', cleaned.get('provider', 'openai-compatible'))
        self._set_param('ai_base_url', cleaned.get('base_url', ''))
        self._set_param('ai_model', cleaned.get('model', ''))
        self._set_param('ai_api_key', cleaned.get('api_key', ''), is_secret=True)
        self._set_param('ai_auth_header', cleaned.get('auth_header', 'Authorization'))
        self._set_param('ai_auth_prefix', cleaned.get('auth_prefix', 'Bearer'))
        self._set_param('ai_system_prompt', cleaned.get('system_prompt', ''))
        self._set_param('ai_enabled', 'true' if cleaned.get('enabled') else 'false')
        for name in ('gapgpt', 'avalai'):
            self._set_param(f'ai_{name}_key', (cleaned.get(f'{name}_key') or '').strip(), is_secret=True)
            self._set_param(f'ai_{name}_model', (cleaned.get(f'{name}_model') or '').strip() or 'gpt-4o-mini')
            self._set_param(f'ai_{name}_enabled', 'true' if cleaned.get(f'{name}_enabled') else 'false')
        self._set_param('ai_order', cleaned.get('order') or 'primary')
        self._set_param('ai_chat_enabled', 'true' if cleaned.get('chat_enabled') else 'false')
        from apps.core import ai_limits
        for feature in ai_limits.FEATURES:
            self._set_param(f'ai_feat_{feature}_enabled',
                            'true' if cleaned.get(f'feat_{feature}_enabled') else 'false')
            self._set_param(f'ai_feat_{feature}_roles', ','.join(cleaned.get(f'feat_{feature}_roles') or []))
            self._set_param(f'ai_feat_{feature}_daily', cleaned.get(f'feat_{feature}_daily') or 0)
        for key in ('chat_per_visitor', 'chat_total'):
            value = cleaned.get(key)
            self._set_param(f'ai_{key}', ai_limits.CHAT_DEFAULTS[f'ai_{key}'] if value is None else value)
        from django.core.cache import cache
        cache.delete('ai:chat-enabled')
        messages.success(self.request, _('تنظیمات هوش مصنوعی ذخیره شد.'))
        return super().form_valid(form)


class IntegrationSettingsForm(forms.Form):
    """SMS and Shahkar (identity) service configuration, stored as SystemParameter."""

    # --- SMS ---
    sms_enabled = forms.BooleanField(label=_('فعال‌سازی ارسال پیامک'), required=False)
    sms_provider = forms.ChoiceField(
        label=_('سرویس پیامک'),
        choices=[
            ('console', _('کنسول (فقط لاگ – تست)')),
            ('iranpayamak', _('ایران‌پیامک / فراز اس‌ام‌اس')),
            ('melipayamak', _('ملی پیامک')),
            ('http', _('HTTP عمومی (سفارشی)')),
        ],
    )
    sms_base_url = forms.CharField(
        label=_('آدرس سرویس پیامک (URL)'), required=False,
        help_text=_('برای ایران‌پیامک و ملی پیامک خالی بگذارید؛ آدرس رسمی به‌صورت خودکار استفاده می‌شود.'))
    sms_username = forms.CharField(
        label=_('نام کاربری پنل پیامک'), required=False,
        help_text=_('فقط برای ملی پیامک: نام کاربری حساب شما در melipayamak.com.'))
    sms_api_key = forms.CharField(
        label=_('کلید API / رمز عبور پیامک'), required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text=_('ایران‌پیامک: کلید Api-Key از پنل — ملی پیامک: رمز عبور حساب شما.'))
    sms_sender = forms.CharField(
        label=_('شمارهٔ فرستنده / خط'), required=False,
        help_text=_('خط ارسال شما در پنل (مثلاً ‎90008361‎). برای ارسال با الگو لازم نیست.'))
    sms_pattern_code = forms.CharField(
        label=_('کد الگوی OTP'), required=False,
        help_text=_('کد الگوی تأییدشده برای کد ورود. ایران‌پیامک: مثل eVGPFLbu9C — ملی پیامک: شناسهٔ عددی الگو (bodyId).'))
    sms_otp_key = forms.CharField(
        label=_('کلید رمز یکبارمصرف ملی پیامک'), required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text=_('بخش آخر آدرس console.melipayamak.com/api/send/otp/… — اگر پر باشد، کدها را خود ملی پیامک می‌سازد و می‌فرستد.'))
    sms_pattern_var = forms.CharField(
        label=_('نام متغیر الگو'), required=False,
        help_text=_('نام متغیر داخل الگو که کد در آن قرار می‌گیرد (پیش‌فرض: code).'))

    # --- Map (map.ir) ---
    map_api_key = forms.CharField(
        label=_('کلید API نقشه (map.ir)'), required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text=_('برای کاشی‌های نقشه و تبدیل مختصات به آدرس.'))
    tomtom_api_key = forms.CharField(
        label=_('کلید API تام‌تام (نقشهٔ ماهواره‌ای)'), required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text=_('منبع اول حالت ماهواره. اگر خالی باشد یا جواب ندهد، از گوگل و بعد نقشهٔ معمولی استفاده می‌شود.'))
    neshan_api_key = forms.CharField(
        label=_('کلید API نشان'), required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text=_('کلید سرویس (service.…) از پنل توسعه‌دهندگان نشان؛ پشتیبان تبدیل مختصات به آدرس.'))
    balad_api_key = forms.CharField(
        label=_('کلید API بلد'), required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text=_('فعلاً فقط ذخیره می‌شود؛ پس از دریافت مستندات API بلد به سامانه وصل می‌شود.'))

    # --- Shahkar (identity verification) ---
    shahkar_enabled = forms.BooleanField(label=_('فعال‌سازی احراز هویت شاهکار'), required=False)
    shahkar_provider = forms.ChoiceField(
        label=_('سرویس احراز هویت'),
        choices=[('mock', _('آزمایشی (بدون تماس واقعی)')), ('shabanic', _('شبانیک (شاهکار)'))],
    )
    shahkar_base_url = forms.CharField(label=_('آدرس API شاهکار (URL)'), required=False)
    shahkar_api_key = forms.CharField(
        label=_('توکن شاهکار'), required=False, widget=forms.PasswordInput(render_value=True))
    shahkar_mock_result = forms.BooleanField(
        label=_('در حالت آزمایشی، نتیجه موفق باشد'), required=False)

    # --- Payment gateway ---
    payment_enabled = forms.BooleanField(label=_('فعال‌سازی درگاه پرداخت'), required=False)
    payment_provider = forms.ChoiceField(
        label=_('درگاه پرداخت'),
        choices=[
            ('internal', _('داخلی (شبیه‌ساز – بدون پرداخت واقعی)')),
            ('zarinpal', _('زرین‌پال')),
            ('jibit', _('جیبیت')),
            ('digipay', _('دیجی‌پی')),
        ],
    )
    payment_merchant_id = forms.CharField(
        label=_('کد پذیرنده / کلید درگاه'), required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text=_('زرین‌پال: Merchant ID — جیبیت: apiKey — دیجی‌پی: client id.'))
    payment_api_key = forms.CharField(
        label=_('رمز درگاه (Secret)'), required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text=_('جیبیت: secretKey — دیجی‌پی: client secret. برای زرین‌پال لازم نیست.'))
    payment_username = forms.CharField(
        label=_('نام کاربری درگاه'), required=False,
        help_text=_('فقط دیجی‌پی.'))
    payment_password = forms.CharField(
        label=_('رمز عبور درگاه'), required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text=_('فقط دیجی‌پی.'))
    payment_site_url = forms.CharField(
        label=_('آدرس سایت برای بازگشت از درگاه'), required=False,
        help_text=_('مثلاً https://pars-tida.ir — بدون اسلش پایانی.'))
    payment_sandbox = forms.BooleanField(
        label=_('حالت آزمایشی (sandbox)'), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault('class', 'form-select')
            else:
                field.widget.attrs.setdefault('class', 'form-control')


def _jwt_expiry(token: str):
    """Expiry of a JWT-style key (map.ir keys are JWTs), or None if unreadable.

    Only the payload's `exp` is read; the signature is not checked, because
    this is just a reminder shown to the admin.
    """
    import base64
    import datetime
    import json
    try:
        payload = token.strip().split('.')[1]
        payload += '=' * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload))['exp']
        return datetime.datetime.fromtimestamp(int(exp), tz=datetime.timezone.utc)
    except (IndexError, KeyError, ValueError, TypeError):
        return None


def store_setting(key, value, is_secret=False):
    SystemParameter.objects.update_or_create(
        key=key,
        defaults={'value': str(value), 'description': 'Integration settings', 'is_secret': is_secret},
    )


def _readable(field, value):
    if isinstance(field, forms.BooleanField):
        return _('بله') if value == 'true' else _('خیر')
    if isinstance(field, forms.ChoiceField):
        return dict(field.choices).get(value, value)
    return value or '—'


def describe_change_request(change):
    """The request plus readable rows; secret values are never included."""
    fields = IntegrationSettingsForm.base_fields
    current = dict(SystemParameter.objects.filter(key__in=change.changes).values_list('key', 'value'))
    rows = []
    for key, item in change.changes.items():
        field = fields.get(key)
        secret = item.get('secret')
        rows.append({
            'label': field.label if field else key,
            'secret': secret,
            'old': '' if secret else _readable(field, current.get(key, '')),
            'new': '' if secret else _readable(field, item['value']),
        })
    change.rows = rows
    return change


class IntegrationSettingsView(LoginRequiredMixin, TechnicalSettingsMixin, FormView):
    """Settings page for the SMS gateway and the Shahkar identity service."""
    template_name = 'core/integration_settings.html'
    form_class = IntegrationSettingsForm
    success_url = reverse_lazy('core:integration-settings')
    extra_context = {'page_title': _('تنظیمات سرویس‌ها')}

    def _get(self, key, default=''):
        param = SystemParameter.objects.filter(key=key).first()
        return param.value if param else default

    def _set(self, key, value, is_secret=False):
        value = str(value)
        if self.hides_secrets and needs_approval(key):
            if value != self._baseline.get(key, ''):
                self._held[key] = {'value': value, 'secret': is_secret}
            elif not is_secret:
                self._unchanged.add(key)
            return
        store_setting(key, value, is_secret)

    def _hold_for_approval(self):
        """Merge this save into the user's open request, or open one."""
        user = self.request.user
        open_request = SettingChangeRequest.objects.filter(
            requested_by=user, status=SettingChangeRequest.Status.PENDING).first()
        changes = dict(open_request.changes) if open_request else {}
        for key in self._unchanged:
            changes.pop(key, None)
        changes.update(self._held)
        if open_request and not changes:
            open_request.delete()
            return None
        if not changes:
            return None
        if open_request:
            open_request.changes = changes
            open_request.save(update_fields=['changes'])
            return open_request
        created = SettingChangeRequest.objects.create(requested_by=user, changes=changes)
        write_audit_log(actor=user, action='settings.change_requested', target_type='setting_change',
                        target_id=str(created.pk), metadata={'keys': sorted(changes)})
        return created

    @staticmethod
    def _secret_fields(form):
        return [name for name, field in form.fields.items()
                if isinstance(field.widget, forms.PasswordInput)]

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if self.hides_secrets:
            for name in self._secret_fields(form):
                make_write_only(form, name)
        return form

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['map_key_expiry'] = _jwt_expiry(self._get('map_api_key', ''))
        from apps.requests.services import sms
        ctx['sms_patterns'] = [
            (_('کد ورود'), sms.pattern_code('sms_pattern_code')),
            (_('کد تأیید قرارداد'), sms.pattern_code(sms.CONTRACT_PATTERN)),
            (_('لینک تکمیل فرم نمایشگاه'), sms.pattern_code(sms.LEAD_LINK_PATTERN)),
            (_('دریافت اطلاعات'), sms.pattern_code(sms.RECEIVED_PATTERN)),
            (_('تغییر وضعیت'), sms.pattern_code(sms.STATUS_PATTERN)),
            (_('پرداخت موفق'), sms.pattern_code(sms.PAYMENT_PATTERN)),
        ]
        if self.hides_secrets:
            ctx['needs_approval_note'] = True
            ctx['my_setting_requests'] = [
                describe_change_request(r) for r in
                SettingChangeRequest.objects.filter(requested_by=self.request.user)[:5]]
        return ctx

    def get_initial(self):
        return {
            'sms_enabled': self._get('sms_enabled', 'true') == 'true',
            'sms_provider': self._get('sms_provider', 'console'),
            'sms_base_url': self._get('sms_base_url', ''),
            'sms_username': self._get('sms_username', ''),
            'sms_api_key': self._get('sms_api_key', ''),
            'sms_sender': self._get('sms_sender', ''),
            'sms_pattern_code': self._get('sms_pattern_code', '') or '520649',
            'sms_pattern_var': self._get('sms_pattern_var', 'code'),
            'sms_otp_key': self._get('sms_otp_key', ''),
            'map_api_key': self._get('map_api_key', ''),
            'neshan_api_key': self._get('neshan_api_key', ''),
            'tomtom_api_key': self._get('map_tomtom_key', ''),
            'balad_api_key': self._get('balad_api_key', ''),
            'shahkar_enabled': self._get('shahkar_enabled', 'true') == 'true',
            'shahkar_provider': self._get('shahkar_provider', 'mock'),
            'shahkar_base_url': self._get('shahkar_base_url', 'https://shabanic.ir/api/v1/shahkar'),
            'shahkar_api_key': self._get('shahkar_api_key', ''),
            'shahkar_mock_result': self._get('shahkar_mock_result', 'true') == 'true',
            'payment_enabled': self._get('payment_enabled', 'false') == 'true',
            'payment_provider': self._get('payment_provider', 'internal'),
            'payment_merchant_id': self._get('payment_merchant_id', ''),
            'payment_api_key': self._get('payment_api_key', ''),
            'payment_username': self._get('payment_username', ''),
            'payment_password': self._get('payment_password', ''),
            'payment_site_url': self._get('payment_site_url', ''),
            'payment_sandbox': self._get('payment_sandbox', 'true') == 'true',
        }

    def form_valid(self, form):
        c = form.cleaned_data
        if self.hides_secrets:
            current = self.get_initial()
            for name in self._secret_fields(form):
                if not (c.get(name) or '').strip():
                    c[name] = current.get(name, '')
            self._baseline = {k: ('true' if v else 'false') if isinstance(v, bool) else str(v)
                              for k, v in current.items()}
            self._held, self._unchanged = {}, set()
        self._set('sms_enabled', 'true' if c.get('sms_enabled') else 'false')
        self._set('sms_provider', c.get('sms_provider', 'console'))
        self._set('sms_base_url', c.get('sms_base_url', ''))
        self._set('sms_username', c.get('sms_username', ''))
        self._set('sms_api_key', c.get('sms_api_key', ''), is_secret=True)
        self._set('sms_sender', c.get('sms_sender', ''))
        self._set('sms_pattern_code', c.get('sms_pattern_code', ''))
        self._set('sms_pattern_var', c.get('sms_pattern_var', '') or 'code')
        otp_key = (c.get('sms_otp_key', '') or '').strip().rstrip('/')
        # Accept the whole console URL pasted in, keep only the key at its end.
        otp_key = otp_key.rsplit('/', 1)[-1]
        self._set('sms_otp_key', otp_key, is_secret=True)
        new_map_key = (c.get('map_api_key', '') or '').strip()
        if new_map_key != self._get('map_api_key', '').strip():
            self._set('map_api_key', new_map_key, is_secret=True)
            # Re-probe tile sources with the new key instead of trusting the old choice.
            from django.core.cache import cache
            from apps.core import tiles
            cache.delete(tiles.UPSTREAM_CACHE_KEY)
        self._set('neshan_api_key', (c.get('neshan_api_key', '') or '').strip(), is_secret=True)
        new_tomtom = (c.get('tomtom_api_key', '') or '').strip()
        if new_tomtom != self._get('map_tomtom_key', '').strip():
            self._set('map_tomtom_key', new_tomtom, is_secret=True)
            # Re-probe satellite sources with the new key right away.
            from django.core.cache import cache
            from apps.core import tiles
            cache.delete(f'{tiles.UPSTREAM_CACHE_KEY}:tomtom-satellite')
        self._set('balad_api_key', (c.get('balad_api_key', '') or '').strip(), is_secret=True)
        self._set('shahkar_enabled', 'true' if c.get('shahkar_enabled') else 'false')
        self._set('shahkar_provider', c.get('shahkar_provider', 'mock'))
        self._set('shahkar_base_url', c.get('shahkar_base_url', ''))
        self._set('shahkar_api_key', c.get('shahkar_api_key', ''), is_secret=True)
        self._set('shahkar_mock_result', 'true' if c.get('shahkar_mock_result') else 'false')
        self._set('payment_enabled', 'true' if c.get('payment_enabled') else 'false')
        self._set('payment_provider', c.get('payment_provider', 'internal'))
        self._set('payment_merchant_id', c.get('payment_merchant_id', ''), is_secret=True)
        self._set('payment_api_key', c.get('payment_api_key', ''), is_secret=True)
        self._set('payment_username', c.get('payment_username', ''))
        self._set('payment_password', c.get('payment_password', ''), is_secret=True)
        self._set('payment_site_url', (c.get('payment_site_url', '') or '').rstrip('/'))
        self._set('payment_sandbox', 'true' if c.get('payment_sandbox') else 'false')
        if self.hides_secrets and self._hold_for_approval():
            messages.info(self.request, _('تغییرات پیامک، شاهکار و درگاه پرداخت ثبت شد و بعد از تأیید مدیر اعمال می‌شود.'))
        else:
            messages.success(self.request, _('تنظیمات سرویس‌ها ذخیره شد.'))
        return super().form_valid(form)


class SettingApprovalListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    template_name = 'core/setting_approvals.html'
    context_object_name = 'pending'

    def get_queryset(self):
        return [describe_change_request(r) for r in SettingChangeRequest.objects.filter(
            status=SettingChangeRequest.Status.PENDING).select_related('requested_by')]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['page_title'] = _('تأیید تغییرات')
        ctx['decided'] = SettingChangeRequest.objects.exclude(
            status=SettingChangeRequest.Status.PENDING).select_related('requested_by', 'decided_by')[:10]
        return ctx


class SettingApprovalDecideView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk, decision):
        Status = SettingChangeRequest.Status
        new_status = {'approve': Status.APPROVED, 'reject': Status.REJECTED}.get(decision)
        if new_status is None:
            raise PermissionDenied
        change = get_object_or_404(SettingChangeRequest, pk=pk)
        # Claim it first so a double click cannot apply it twice.
        claimed = SettingChangeRequest.objects.filter(pk=pk, status=Status.PENDING).update(
            status=new_status, decided_by=request.user, decided_at=timezone.now())
        if not claimed:
            messages.error(request, _('این درخواست قبلاً بررسی شده است.'))
            return redirect('core:setting-approvals')
        if new_status == Status.APPROVED:
            for key, item in change.changes.items():
                store_setting(key, item['value'], item.get('secret', False))
        kept = {key: {**item, 'value': '' if item.get('secret') else item['value']}
                for key, item in change.changes.items()}
        SettingChangeRequest.objects.filter(pk=pk).update(changes=kept)
        write_audit_log(actor=request.user, action=f'settings.change_{new_status}',
                        target_type='setting_change', target_id=str(pk), metadata={'keys': sorted(kept)})
        messages.success(request, _('تغییرات اعمال شد.') if new_status == Status.APPROVED else _('درخواست رد شد.'))
        return redirect('core:setting-approvals')
