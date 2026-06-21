from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, FormView
from django.urls import reverse_lazy
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from .models import SystemParameter, SecuritySetting, APIConnection, ProtocolAdapter, DatabaseBackup, AuditLog, ServerHealthMetric
from django import forms


class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        request = getattr(self, 'request', None)
        user = getattr(request, 'user', None)
        return bool(user and (user.is_superuser or user.has_permission_code('admin.access')))


class SystemParameterForm(forms.ModelForm):
    class Meta:
        model = SystemParameter
        fields = '__all__'


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
    base_url = forms.URLField(label='Base URL', required=True)
    model = forms.CharField(label='Model', required=True)
    api_key = forms.CharField(label='API Key', required=False, widget=forms.PasswordInput(render_value=True))
    auth_header = forms.CharField(label='Auth Header', required=False, initial='Authorization')
    auth_prefix = forms.CharField(label='Auth Prefix', required=False, initial='Bearer')
    system_prompt = forms.CharField(label='System Prompt', required=False, widget=forms.Textarea(attrs={'rows': 4}))
    enabled = forms.BooleanField(label='فعال', required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault('class', 'form-select')
            else:
                field.widget.attrs.setdefault('class', 'form-control')


class SystemParameterListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = SystemParameter
    template_name = 'core/list.html'
    extra_context = {'page_title': _('پارامترهای سیستم'), 'resource_key': 'parameters'}


class SystemParameterCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = SystemParameter
    form_class = SystemParameterForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:parameters')


class SystemParameterUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = SystemParameter
    form_class = SystemParameterForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:parameters')


class SystemParameterDeleteView(LoginRequiredMixin, AdminRequiredMixin, DeleteView):
    model = SystemParameter
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('core:parameters')


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


class APIConnectionListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = APIConnection
    template_name = 'core/list.html'
    extra_context = {'page_title': _('اتصالات API'), 'resource_key': 'connections'}


class APIConnectionCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = APIConnection
    form_class = APIConnectionForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:connections')


class APIConnectionUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = APIConnection
    form_class = APIConnectionForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:connections')


class APIConnectionDeleteView(LoginRequiredMixin, AdminRequiredMixin, DeleteView):
    model = APIConnection
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('core:connections')


class InverterAPIConnectionView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
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


class ProtocolAdapterListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = ProtocolAdapter
    template_name = 'core/list.html'
    extra_context = {'page_title': _('پروتکل‌ها'), 'resource_key': 'protocols'}


class ProtocolAdapterCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = ProtocolAdapter
    form_class = ProtocolAdapterForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:protocols')


class ProtocolAdapterUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = ProtocolAdapter
    form_class = ProtocolAdapterForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('core:protocols')


class ProtocolAdapterDeleteView(LoginRequiredMixin, AdminRequiredMixin, DeleteView):
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
        }

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
        messages.success(self.request, _('تنظیمات هوش مصنوعی ذخیره شد.'))
        return super().form_valid(form)


class IntegrationSettingsForm(forms.Form):
    """SMS and Shahkar (identity) service configuration, stored as SystemParameter."""

    # --- SMS ---
    sms_enabled = forms.BooleanField(label=_('فعال‌سازی ارسال پیامک'), required=False)
    sms_provider = forms.ChoiceField(
        label=_('سرویس پیامک'),
        choices=[('console', _('کنسول (فقط لاگ – تست)')), ('http', _('HTTP (سرویس واقعی)'))],
    )
    sms_base_url = forms.CharField(label=_('آدرس سرویس پیامک (URL)'), required=False)
    sms_api_key = forms.CharField(
        label=_('کلید API پیامک'), required=False, widget=forms.PasswordInput(render_value=True))
    sms_sender = forms.CharField(label=_('شمارهٔ فرستنده'), required=False)

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs.setdefault('class', 'form-select')
            else:
                field.widget.attrs.setdefault('class', 'form-control')


class IntegrationSettingsView(LoginRequiredMixin, AdminRequiredMixin, FormView):
    """Settings page for the SMS gateway and the Shahkar identity service."""
    template_name = 'core/integration_settings.html'
    form_class = IntegrationSettingsForm
    success_url = reverse_lazy('core:integration-settings')
    extra_context = {'page_title': _('تنظیمات سرویس‌ها')}

    def _get(self, key, default=''):
        param = SystemParameter.objects.filter(key=key).first()
        return param.value if param else default

    def _set(self, key, value, is_secret=False):
        SystemParameter.objects.update_or_create(
            key=key,
            defaults={'value': str(value), 'description': 'Integration settings', 'is_secret': is_secret},
        )

    def get_initial(self):
        return {
            'sms_enabled': self._get('sms_enabled', 'true') == 'true',
            'sms_provider': self._get('sms_provider', 'console'),
            'sms_base_url': self._get('sms_base_url', ''),
            'sms_api_key': self._get('sms_api_key', ''),
            'sms_sender': self._get('sms_sender', ''),
            'shahkar_enabled': self._get('shahkar_enabled', 'true') == 'true',
            'shahkar_provider': self._get('shahkar_provider', 'mock'),
            'shahkar_base_url': self._get('shahkar_base_url', 'https://shabanic.ir/api/v1/shahkar'),
            'shahkar_api_key': self._get('shahkar_api_key', ''),
            'shahkar_mock_result': self._get('shahkar_mock_result', 'true') == 'true',
        }

    def form_valid(self, form):
        c = form.cleaned_data
        self._set('sms_enabled', 'true' if c.get('sms_enabled') else 'false')
        self._set('sms_provider', c.get('sms_provider', 'console'))
        self._set('sms_base_url', c.get('sms_base_url', ''))
        self._set('sms_api_key', c.get('sms_api_key', ''), is_secret=True)
        self._set('sms_sender', c.get('sms_sender', ''))
        self._set('shahkar_enabled', 'true' if c.get('shahkar_enabled') else 'false')
        self._set('shahkar_provider', c.get('shahkar_provider', 'mock'))
        self._set('shahkar_base_url', c.get('shahkar_base_url', ''))
        self._set('shahkar_api_key', c.get('shahkar_api_key', ''), is_secret=True)
        self._set('shahkar_mock_result', 'true' if c.get('shahkar_mock_result') else 'false')
        messages.success(self.request, _('تنظیمات سرویس‌ها ذخیره شد.'))
        return super().form_valid(form)
