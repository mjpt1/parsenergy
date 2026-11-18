from django.contrib import messages
from django.contrib.auth import login
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, FormView

from .forms import (AccountForm, LoginForm, RegisterForm, RoleForm, PermissionForm,
                    StaffCreateForm, UserRoleAssignForm, RolePermissionAssignForm,
                    clean_staff_mobile)
from .models import User, Role, Permission


class UserLoginView(LoginView):
    """The staff door: username + password.

    Customers come in through `requests:otp-login` with a mobile and a texted
    code. Both entrances are linked from the public shell so nobody has to
    guess which one is theirs.
    """

    template_name = 'accounts/login.html'
    authentication_form = LoginForm
    # Renders inside the customer shell, but it is not a customer account
    # page — so no "my requests / my plant" tab row.
    extra_context = {'portal_no_tabs': True, 'page_title': 'ورود پرسنل'}


class UserLogoutView(LogoutView):
    next_page = reverse_lazy('accounts:login')


def register_view(request):
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = RegisterForm()
    return render(request, 'accounts/register.html', {'form': form})


@login_required
def profile_view(request):
    """Editable profile. Customers get their full contact/identity profile
    (seeded from the request form they already filled); staff get account basics."""
    from django.utils import timezone

    from apps.requests.forms import ProfileCompletionForm
    from apps.requests.models import UserProfileCompletion

    user = request.user
    is_customer = user.role in (User.Role.OWNER, User.Role.CUSTOMER)
    account_form = AccountForm(instance=user)
    profile_form = None
    profile = UserProfileCompletion.ensure_for(user) if is_customer else None

    if request.method == 'POST':
        account_form = AccountForm(request.POST, instance=user)
        forms_ok = account_form.is_valid()
        if is_customer:
            profile_form = ProfileCompletionForm(request.POST, instance=profile)
            forms_ok = forms_ok & profile_form.is_valid()
        if forms_ok:
            account_form.save()
            if is_customer:
                p = profile_form.save(commit=False)
                p.user = user
                p.is_completed = True
                p.completed_at = p.completed_at or timezone.now()
                p.save()
                if p.full_name and not (user.first_name or user.last_name):
                    user.first_name = p.full_name
                    user.save(update_fields=['first_name'])
            messages.success(request, 'پروفایل با موفقیت ذخیره شد.')
            return redirect('accounts:profile')
    elif is_customer:
        profile_form = ProfileCompletionForm(instance=profile)

    return render(request, 'accounts/profile.html', {
        'user': user,
        'account_form': account_form,
        'profile_form': profile_form,
        'is_customer': is_customer,
        'base_template': ('base_portal.html' if is_customer or user.role == User.Role.CONTRACTOR
                          else 'base.html'),
        'portal_tab': 'profile',
        'page_title': 'پروفایل من',
    })


class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        user = getattr(self.request, 'user', None)
        return bool(user and (user.is_superuser or user.has_permission_code('admin.access')))


class UserListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = User
    template_name = 'accounts/users.html'
    paginate_by = 25
    ordering = ['-date_joined']


class RoleListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = Role
    template_name = 'accounts/roles_list.html'
    paginate_by = 25
    ordering = ['name']


class RoleCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = Role
    form_class = RoleForm
    template_name = 'accounts/role_form.html'
    success_url = reverse_lazy('accounts:roles')


class RoleUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = Role
    form_class = RoleForm
    template_name = 'accounts/role_form.html'
    success_url = reverse_lazy('accounts:roles')


class RoleDeleteView(LoginRequiredMixin, AdminRequiredMixin, DeleteView):
    model = Role
    template_name = 'accounts/role_confirm_delete.html'
    success_url = reverse_lazy('accounts:roles')


class PermissionListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = Permission
    template_name = 'accounts/permissions_list.html'
    paginate_by = 25
    ordering = ['code']


class PermissionCreateView(LoginRequiredMixin, AdminRequiredMixin, CreateView):
    model = Permission
    form_class = PermissionForm
    template_name = 'accounts/permission_form.html'
    success_url = reverse_lazy('accounts:permissions')


class PermissionUpdateView(LoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = Permission
    form_class = PermissionForm
    template_name = 'accounts/permission_form.html'
    success_url = reverse_lazy('accounts:permissions')


class PermissionDeleteView(LoginRequiredMixin, AdminRequiredMixin, DeleteView):
    model = Permission
    template_name = 'accounts/permission_confirm_delete.html'
    success_url = reverse_lazy('accounts:permissions')


class UserRoleAssignView(LoginRequiredMixin, AdminRequiredMixin, FormView):
    template_name = 'accounts/user_roles.html'
    form_class = UserRoleAssignForm

    def dispatch(self, request, *args, **kwargs):
        self.target_user = get_object_or_404(User, pk=kwargs.get('pk'))
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {'roles': self.target_user.roles.all()}

    def form_valid(self, form):
        roles = form.cleaned_data.get('roles')
        self.target_user.roles.set(roles)
        return redirect('accounts:users')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['target_user'] = self.target_user
        return context


class RolePermissionAssignView(LoginRequiredMixin, AdminRequiredMixin, FormView):
    template_name = 'accounts/role_permissions.html'
    form_class = RolePermissionAssignForm

    def dispatch(self, request, *args, **kwargs):
        self.target_role = get_object_or_404(Role, pk=kwargs.get('pk'))
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {'permissions': self.target_role.role_permissions.values_list('permission', flat=True)}

    def form_valid(self, form):
        permissions = form.cleaned_data.get('permissions')
        self.target_role.role_permissions.all().delete()
        for perm in permissions:
            self.target_role.role_permissions.create(permission=perm)
        return redirect('accounts:roles')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['target_role'] = self.target_role
        return context


# --------------------------------------------------------------------------- #
# Simple staff/user management: set a user's main role + extra access toggles
# --------------------------------------------------------------------------- #

def _is_management(user):
    return bool(user and (user.is_superuser or user.has_permission_code('admin.access')))


class StaffManageListView(LoginRequiredMixin, AdminRequiredMixin, ListView):
    model = User
    template_name = 'accounts/staff_manage_list.html'
    paginate_by = 50
    ordering = ['-date_joined']

    def get_queryset(self):
        qs = super().get_queryset()
        query = (self.request.GET.get('q') or '').strip()
        if query:
            qs = qs.filter(
                Q(username__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
            )
        role = (self.request.GET.get('role') or '').strip()
        if role in dict(User.Role.choices):
            qs = qs.filter(role=role)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['role_labels'] = dict(User.Role.choices)
        ctx['role_choices'] = User.Role.choices
        ctx['search_query'] = (self.request.GET.get('q') or '').strip()
        ctx['role_filter'] = (self.request.GET.get('role') or '').strip()
        return ctx


@login_required
def staff_manage_create(request):
    """Create a staff/customer account from the Persian panel.

    Same audience as `staff_manage_edit` (superuser or `admin.access`). The
    form intentionally cannot grant `is_staff`/`is_superuser`, so this screen
    can't be used to escalate privileges — those stay in Django admin.
    """
    if not _is_management(request.user):
        raise PermissionDenied
    if request.method == 'POST':
        form = StaffCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(
                request, f'کاربر «{user.username}» با نقش «{user.get_role_display()}» ساخته شد.')
            return redirect('accounts:staff-manage')
    else:
        form = StaffCreateForm()
    return render(request, 'accounts/staff_manage_create.html', {
        'form': form,
        'page_title': 'ساخت کاربر جدید',
    })


@login_required
def staff_manage_edit(request, pk):
    if not _is_management(request.user):
        raise PermissionDenied
    target = get_object_or_404(User, pk=pk)
    permissions = Permission.objects.order_by('code')
    if request.method == 'POST':
        if target.is_superuser and target != request.user:
            messages.error(request, 'کاربر سوپرادمین از این بخش قابل ویرایش نیست.')
            return redirect('accounts:staff-manage')
        # The mobile is a way in (sign-in by texted code), so it is editable
        # here and validated the same way the create form validates it.
        raw_mobile = request.POST.get('phone_number', '')
        if raw_mobile.strip():
            try:
                target.phone_number = clean_staff_mobile(raw_mobile, instance=target)
                target.save(update_fields=['phone_number'])
            except ValidationError as exc:
                messages.error(request, '; '.join(exc.messages))
                return redirect('accounts:staff-manage-edit', pk=pk)
        new_role = request.POST.get('role')
        if new_role in dict(User.Role.choices):
            target.role = new_role
            target.save(update_fields=['role'])
        selected = request.POST.getlist('extra_permissions')
        target.extra_permissions.set(Permission.objects.filter(code__in=selected))
        messages.success(request, 'دسترسی‌های کاربر به‌روزرسانی شد.')
        return redirect('accounts:staff-manage')
    return render(request, 'accounts/staff_manage_edit.html', {
        'target': target,
        'role_choices': User.Role.choices,
        'permissions': permissions,
        'current_perms': set(target.extra_permissions.values_list('code', flat=True)),
    })


def _guard_target(request, target, *, action):
    """Shared safety rules for the destructive user actions.

    Returns an error message, or None when the action may proceed. Superusers
    are only ever touched by another superuser, nobody can lock themselves out,
    and the last remaining superuser cannot be removed or disabled.
    """
    if target.is_superuser and not request.user.is_superuser:
        return 'کاربر سوپرادمین فقط توسط سوپرادمین دیگری قابل تغییر است.'
    if target == request.user:
        return 'نمی‌توانید این کار را روی حساب خودتان انجام دهید.'
    if action in ('delete', 'deactivate') and target.is_superuser:
        remaining = User.objects.filter(is_superuser=True, is_active=True).exclude(pk=target.pk).count()
        if not remaining:
            return 'این تنها سوپرادمین فعال سامانه است و نمی‌توان آن را حذف یا غیرفعال کرد.'
    return None


@login_required
def staff_manage_delete(request, pk):
    """Delete a user account from the Persian panel (POST only)."""
    if not _is_management(request.user):
        raise PermissionDenied
    target = get_object_or_404(User, pk=pk)
    if request.method != 'POST':
        return render(request, 'accounts/staff_manage_delete.html', {'target': target})
    error = _guard_target(request, target, action='delete')
    if error:
        messages.error(request, error)
    else:
        username = target.username
        try:
            target.delete()
            messages.success(request, f'کاربر «{username}» حذف شد.')
        except ProtectedError:
            messages.error(request, 'این پیمانکار سابقهٔ کار دارد و حذف نمی‌شود؛ حساب را غیرفعال کنید.')
    return redirect('accounts:staff-manage')


@login_required
def staff_manage_toggle_active(request, pk):
    """Enable or disable an account without deleting its history (POST only)."""
    if not _is_management(request.user):
        raise PermissionDenied
    if request.method != 'POST':
        return redirect('accounts:staff-manage')
    target = get_object_or_404(User, pk=pk)
    error = _guard_target(request, target, action='deactivate' if target.is_active else 'activate')
    if error:
        messages.error(request, error)
    else:
        target.is_active = not target.is_active
        target.save(update_fields=['is_active'])
        state = 'فعال' if target.is_active else 'غیرفعال'
        messages.success(request, f'حساب «{target.username}» {state} شد.')
    return redirect('accounts:staff-manage')


@login_required
def staff_manage_reset_password(request, pk):
    """Set a new password for another user (POST only)."""
    if not _is_management(request.user):
        raise PermissionDenied
    target = get_object_or_404(User, pk=pk)
    if request.method != 'POST':
        return render(request, 'accounts/staff_manage_password.html', {'target': target})
    if target.is_superuser and not request.user.is_superuser:
        messages.error(request, 'رمز سوپرادمین فقط توسط سوپرادمین دیگری قابل تغییر است.')
        return redirect('accounts:staff-manage')
    password = request.POST.get('password') or ''
    if len(password) < 8:
        messages.error(request, 'رمز عبور باید حداقل ۸ کاراکتر باشد.')
        return redirect('accounts:staff-manage-password', pk=target.pk)
    target.set_password(password)
    target.save(update_fields=['password'])
    messages.success(request, f'رمز عبور «{target.username}» تغییر کرد.')
    return redirect('accounts:staff-manage')
