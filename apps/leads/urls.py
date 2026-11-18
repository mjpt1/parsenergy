"""Lead URLs.

The capture paths carry an unguessable token and are the only way in — they are
never linked from the site, and robots.txt plus an `X-Robots-Tag` header keep
them out of search engines.

There is no lead list here: a capture becomes an ordinary request, so it is
listed and worked on at `requests:admin-list` with every other lead. The only
panel screen left is the QR administration.
"""
from django.urls import path

from . import views

app_name = 'leads'

urlpatterns = [
    # Public, token-addressed capture (QR codes point at `capture`).
    path('go/<str:token>/', views.capture, name='capture'),
    path('ok/<str:token>/', views.captured, name='captured'),
    path('ok/<str:token>/sms/', views.send_resume_link, name='send-resume-link'),
    path('f/<str:token>/', views.detail_form, name='detail-form'),
    path('done/<str:token>/', views.done, name='done'),

    # QR administration (management only).
    path('panel/sources/', views.source_list, name='sources'),
    path('panel/followup/', views.followup, name='followup'),
    path('panel/marketers/', views.marketer_report, name='marketer-report'),
    path('panel/marketers/<int:pk>/', views.marketer_detail, name='marketer-detail'),
]
