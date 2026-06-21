from django.urls import path
from .views import analytics_dashboard, ai_analysis

app_name = 'analytics'

urlpatterns = [
    path('', analytics_dashboard, name='dashboard'),
    path('plant/<int:plant_id>/', analytics_dashboard, name='plant-dashboard'),
    path('ai/', ai_analysis, name='ai-analysis'),
]
