from django.urls import path
from .views import analytics_dashboard, ai_analysis
from .traffic_views import pixel, traffic_report
from .ai_views import ai_chat, ai_task

app_name = 'analytics'

urlpatterns = [
    path('', analytics_dashboard, name='dashboard'),
    path('plant/<int:plant_id>/', analytics_dashboard, name='plant-dashboard'),
    path('ai/', ai_analysis, name='ai-analysis'),
    path('ai/task/', ai_task, name='ai-task'),
    path('ai/chat/', ai_chat, name='ai-chat'),
    path('traffic/', traffic_report, name='traffic'),
    path('t.gif', pixel, name='pixel'),
]
