from django.urls import path

from . import views_admin as admin_views
from . import views_user as user_views

app_name = 'requests'

urlpatterns = [
    # --- Admin (inside the existing admin panel) ---
    path('manage/', admin_views.RequestAdminListView.as_view(), name='admin-list'),
    path('manage/offers/', admin_views.OfferAdminListView.as_view(), name='admin-offers'),
    path('manage/payments/', admin_views.PaymentAdminListView.as_view(), name='admin-payments'),
    path('manage/contracts/', admin_views.ContractAdminListView.as_view(), name='admin-contracts'),
    path('manage/sms-logs/', admin_views.SmsLogAdminListView.as_view(), name='admin-sms-logs'),

    # Contract templates (multiple, named)
    path('manage/templates/', admin_views.ContractTemplateListView.as_view(), name='admin-templates'),
    path('manage/templates/add/', admin_views.ContractTemplateCreateView.as_view(), name='admin-template-add'),
    path('manage/templates/<int:pk>/edit/', admin_views.ContractTemplateEditView.as_view(), name='admin-template-edit'),
    path('manage/templates/<int:pk>/activate/', admin_views.ContractTemplateActivateView.as_view(), name='admin-template-activate'),
    path('manage/templates/<int:pk>/delete/', admin_views.ContractTemplateDeleteView.as_view(), name='admin-template-delete'),

    # Contract settings (company header / margins / customer page)
    path('manage/contract-settings/', admin_views.ContractSettingsView.as_view(), name='contract-settings'),

    # Tickets (admin)
    path('manage/tickets/', admin_views.TicketAdminListView.as_view(), name='admin-tickets'),
    path('manage/tickets/<int:pk>/', admin_views.TicketAdminDetailView.as_view(), name='admin-ticket-detail'),
    path('manage/tickets/<int:pk>/reply/', admin_views.TicketAdminReplyView.as_view(), name='admin-ticket-reply'),
    path('manage/tickets/<int:pk>/status/', admin_views.TicketAdminStatusView.as_view(), name='admin-ticket-status'),

    path('manage/<int:pk>/', admin_views.RequestAdminDetailView.as_view(), name='admin-detail'),
    path('manage/<int:pk>/offers/add/', admin_views.OfferAddView.as_view(), name='admin-offer-add'),
    path('manage/offers/<int:pk>/toggle/', admin_views.OfferToggleView.as_view(), name='admin-offer-toggle'),
    path('manage/offers/<int:pk>/issue-contract/', admin_views.OfferIssueContractView.as_view(), name='admin-offer-issue-contract'),
    path('manage/<int:pk>/status/', admin_views.RequestStatusChangeView.as_view(), name='admin-status'),

    # --- User panel ("درخواست‌های من") ---
    path('submit/', user_views.submit_request, name='submit'),
    path('login/', user_views.otp_login, name='otp-login'),
    path('verify/', user_views.verify, name='verify'),
    path('verify/resend/', user_views.resend_otp, name='resend-otp'),
    path('mine/', user_views.MyRequestListView.as_view(), name='my-list'),
    path('mine/<int:pk>/', user_views.MyRequestDetailView.as_view(), name='my-detail'),
    path('mine/<int:pk>/select-offer/', user_views.select_offer, name='select-offer'),
    path('mine/<int:pk>/contract/', user_views.contract_view, name='contract'),
    path('mine/<int:pk>/contract/print/', user_views.contract_print, name='contract-print'),
    path('mine/<int:pk>/contract/word/', user_views.contract_word, name='contract-word'),
    path('mine/<int:pk>/contract/send-otp/', user_views.send_contract_otp, name='contract-send-otp'),
    path('mine/<int:pk>/contract/approve/', user_views.approve_contract, name='contract-approve'),
    path('mine/<int:pk>/messages/', user_views.messages_view, name='messages'),
    path('mine/<int:pk>/pay/', user_views.pay_start, name='pay-start'),
    path('pay/<uuid:token>/', user_views.pay_page, name='pay'),
    path('pay/<uuid:token>/callback/', user_views.pay_callback, name='pay-callback'),
    path('profile/complete/', user_views.complete_profile, name='profile-complete'),

    # Tickets (customer)
    path('tickets/', user_views.MyTicketListView.as_view(), name='my-tickets'),
    path('tickets/new/', user_views.ticket_create, name='ticket-create'),
    path('tickets/<int:pk>/', user_views.MyTicketDetailView.as_view(), name='ticket-detail'),
    path('tickets/<int:pk>/reply/', user_views.ticket_reply, name='ticket-reply'),
]
