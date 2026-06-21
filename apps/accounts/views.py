from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, FormView

from .forms import LoginForm, RegisterForm, RoleForm, PermissionForm, UserRoleAssignForm, RolePermissionAssignForm
from .models import User, Role, Permission


class UserLoginView(LoginView):
    template_name = 'accounts/login.html'
    authentication_form = LoginForm


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
    return render(request, 'accounts/profile.html', {'user': request.user})


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
