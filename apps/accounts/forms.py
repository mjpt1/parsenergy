import re

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.utils.translation import gettext_lazy as _

from .models import User, Role, Permission

_FA_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def clean_staff_mobile(raw, instance=None):
    """Normalise and check a staff mobile.

    Accepts the shapes people actually type — Persian digits, +98, 0098, a
    bare 9xxxxxxxxx — and stores one canonical 09xxxxxxxxx. It must be unique,
    because the number is a way in: two accounts sharing one mobile would make
    "sign in with a texted code" ambiguous.
    """
    value = (raw or '').translate(_FA_DIGITS)
    value = re.sub(r'[\s\-()]', '', value)
    if value.startswith('+98'):
        value = '0' + value[3:]
    elif value.startswith('0098'):
        value = '0' + value[4:]
    elif value.startswith('98') and len(value) == 12:
        value = '0' + value[2:]
    elif value.startswith('9') and len(value) == 10:
        value = '0' + value
    if not re.fullmatch(r'09\d{9}', value):
        raise forms.ValidationError(_('شمارهٔ موبایل را درست وارد کنید (مثل ۰۹۱۲۳۴۵۶۷۸۹).'))
    clash = User.objects.filter(phone_number=value)
    if instance is not None and instance.pk:
        clash = clash.exclude(pk=instance.pk)
    if clash.exists():
        raise forms.ValidationError(_('این شماره قبلاً برای کاربر دیگری ثبت شده است.'))
    return value


class LoginForm(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={'class': 'form-control'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}))


class RegisterForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('username', 'email', 'phone_number')

    def save(self, commit=True):
        user = super().save(commit=False)
        # Public registration must never grant elevated roles.
        user.role = User.Role.OWNER
        if commit:
            user.save()
        return user


class StaffCreateForm(UserCreationForm):
    """Admin-side "add a user" form for the Persian panel.

    Unlike public `RegisterForm` (which pins everyone to OWNER), management may
    pick the new user's role here. `is_staff`/`is_superuser` are deliberately
    absent — Django-admin access and superuser rights stay a Django-admin-only
    decision so this screen can't be used to escalate privileges.
    """

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'phone_number', 'role')
        labels = {
            'username': _('نام کاربری'),
            'first_name': _('نام'),
            'last_name': _('نام خانوادگی'),
            'email': _('ایمیل'),
            'phone_number': _('شماره موبایل'),
            'role': _('نقش'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].label = _('رمز عبور')
        self.fields['password2'].label = _('تکرار رمز عبور')
        for name in ('first_name', 'last_name', 'email'):
            self.fields[name].required = False
        # The mobile is how a staff member signs in with a texted code instead
        # of a password, so an account without one is half-built. It is also
        # what tells the customer login "this number is staff, sign them into
        # their real account" rather than opening a second, customer one.
        self.fields['phone_number'].required = True
        self.fields['phone_number'].help_text = _(
            'با همین شماره هم می‌تواند با کد پیامکی وارد شود.')
        self.fields['phone_number'].widget.attrs.setdefault('placeholder', '۰۹۱۲۳۴۵۶۷۸۹')
        self.fields['phone_number'].widget.attrs.setdefault('inputmode', 'numeric')
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.Select):
                widget.attrs.setdefault('class', 'form-select')
            else:
                widget.attrs.setdefault('class', 'form-control')

    def clean_phone_number(self):
        return clean_staff_mobile(self.cleaned_data.get('phone_number'))


class AccountForm(forms.ModelForm):
    """Editable account basics shared by every role."""

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'phone_number')
        labels = {
            'first_name': 'نام',
            'last_name': 'نام خانوادگی',
            'email': 'ایمیل',
            'phone_number': 'تلفن تماس',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')


class RoleForm(forms.ModelForm):
    class Meta:
        model = Role
        fields = ('name', 'description', 'is_system')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault('class', 'form-check-input')
            else:
                field.widget.attrs.setdefault('class', 'form-control')


class PermissionForm(forms.ModelForm):
    class Meta:
        model = Permission
        fields = ('code', 'description')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-control')


class UserRoleAssignForm(forms.Form):
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select'}),
        label='نقش‌ها',
    )


class RolePermissionAssignForm(forms.Form):
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select'}),
        label='مجوزها',
    )
