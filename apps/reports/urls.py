from django.urls import path
from .views import report_center, export_pdf, export_excel, proposal

app_name = 'reports'

urlpatterns = [
    path('', report_center, name='center'),
    path('proposal/', proposal, name='proposal'),
    path('<int:plant_id>/pdf/', export_pdf, name='pdf'),
    path('<int:plant_id>/excel/', export_excel, name='excel'),
]
