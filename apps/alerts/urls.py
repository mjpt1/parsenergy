from django.urls import path
from .views import AlertRuleListView, AlertRuleCreateView, AlertRuleUpdateView, AlertRuleDeleteView, AlertEventListView, NotificationListView

app_name = 'alerts'

urlpatterns = [
    path('', AlertRuleListView.as_view(), name='list'),
    path('create/', AlertRuleCreateView.as_view(), name='create'),
    path('<int:pk>/edit/', AlertRuleUpdateView.as_view(), name='edit'),
    path('<int:pk>/delete/', AlertRuleDeleteView.as_view(), name='delete'),
    path('events/', AlertEventListView.as_view(), name='events'),
    path('notifications/', NotificationListView.as_view(), name='notifications'),
]
