from django.urls import path
from .views import (
    VPPListView, VPPCreateView, VPPUpdateView, VPPDeleteView,
    VPPMemberListView, VPPMemberCreateView, VPPMemberUpdateView, VPPMemberDeleteView,
    DispatchScheduleListView, DispatchScheduleCreateView, DispatchScheduleUpdateView, DispatchScheduleDeleteView,
)

app_name = 'vpp'

urlpatterns = [
    path('', VPPListView.as_view(), name='list'),
    path('create/', VPPCreateView.as_view(), name='create'),
    path('<int:pk>/edit/', VPPUpdateView.as_view(), name='edit'),
    path('<int:pk>/delete/', VPPDeleteView.as_view(), name='delete'),
    path('members/', VPPMemberListView.as_view(), name='members'),
    path('members/create/', VPPMemberCreateView.as_view(), name='member-create'),
    path('members/<int:pk>/edit/', VPPMemberUpdateView.as_view(), name='member-edit'),
    path('members/<int:pk>/delete/', VPPMemberDeleteView.as_view(), name='member-delete'),
    path('schedules/', DispatchScheduleListView.as_view(), name='schedules'),
    path('schedules/create/', DispatchScheduleCreateView.as_view(), name='schedule-create'),
    path('schedules/<int:pk>/edit/', DispatchScheduleUpdateView.as_view(), name='schedule-edit'),
    path('schedules/<int:pk>/delete/', DispatchScheduleDeleteView.as_view(), name='schedule-delete'),
]
