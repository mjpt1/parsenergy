from django.urls import path
from .views import (
    UserLoginView, UserLogoutView, register_view, profile_view, UserListView,
    RoleListView, RoleCreateView, RoleUpdateView, RoleDeleteView,
    PermissionListView, PermissionCreateView, PermissionUpdateView, PermissionDeleteView,
    UserRoleAssignView, RolePermissionAssignView,
    StaffManageListView, staff_manage_create, staff_manage_edit,
    staff_manage_delete, staff_manage_reset_password, staff_manage_toggle_active,
)

app_name = 'accounts'

urlpatterns = [
    path('login/', UserLoginView.as_view(), name='login'),
    path('logout/', UserLogoutView.as_view(), name='logout'),
    path('register/', register_view, name='register'),
    path('profile/', profile_view, name='profile'),
    path('users/', UserListView.as_view(), name='users'),
    path('staff/', StaffManageListView.as_view(), name='staff-manage'),
    path('staff/create/', staff_manage_create, name='staff-manage-create'),
    path('staff/<int:pk>/edit/', staff_manage_edit, name='staff-manage-edit'),
    path('staff/<int:pk>/password/', staff_manage_reset_password, name='staff-manage-password'),
    path('staff/<int:pk>/active/', staff_manage_toggle_active, name='staff-manage-active'),
    path('staff/<int:pk>/delete/', staff_manage_delete, name='staff-manage-delete'),
    path('users/<int:pk>/roles/', UserRoleAssignView.as_view(), name='user-roles'),
    path('roles/', RoleListView.as_view(), name='roles'),
    path('roles/<int:pk>/permissions/', RolePermissionAssignView.as_view(), name='role-permissions'),
    path('roles/create/', RoleCreateView.as_view(), name='roles-create'),
    path('roles/<int:pk>/edit/', RoleUpdateView.as_view(), name='roles-edit'),
    path('roles/<int:pk>/delete/', RoleDeleteView.as_view(), name='roles-delete'),
    path('permissions/', PermissionListView.as_view(), name='permissions'),
    path('permissions/create/', PermissionCreateView.as_view(), name='permissions-create'),
    path('permissions/<int:pk>/edit/', PermissionUpdateView.as_view(), name='permissions-edit'),
    path('permissions/<int:pk>/delete/', PermissionDeleteView.as_view(), name='permissions-delete'),
]
