from django.urls import path

from . import views_admin as admin_views
from . import views_delivery as delivery_views
from . import views_project as project_views
from . import views_user as user_views

app_name = 'requests'

urlpatterns = [
    # --- Admin (inside the existing admin panel) ---
    path('manage/', admin_views.RequestAdminListView.as_view(), name='admin-list'),
    path('project/<int:pk>/contract/', project_views.contract_form, name='project-contract'),
    path('project/contracts/<int:pk>/file/', project_views.contract_file, name='project-contract-file'),
    path('project/<int:pk>/documents/add/', project_views.document_add, name='document-add'),
    path('project/documents/<int:pk>/file/', project_views.document_file, name='document-file'),
    path('project/documents/<int:pk>/delete/', project_views.document_delete, name='document-delete'),
    path('project/installments/<int:pk>/receipt/', project_views.receipt_submit, name='installment-receipt'),
    path('project/installments/<int:pk>/receipt-file/', project_views.receipt_file, name='installment-receipt-file'),
    path('project/installments/<int:pk>/review/', project_views.installment_review, name='installment-review'),
    path('project/payments/<int:pk>/review/', project_views.payment_review, name='payment-review'),
    path('contractor/', delivery_views.contractor_home, name='contractor-home'),
    path('contractor/projects/<int:pk>/', delivery_views.contractor_project, name='contractor-project'),
    path('contractor/projects/<int:pk>/report/', delivery_views.contractor_report, name='contractor-report'),
    path('manage/contractors/', delivery_views.contractor_list, name='contractors'),
    path('manage/contractors/<int:pk>/', delivery_views.contractor_detail, name='contractor-detail'),
    path('project/<int:pk>/contractors/add/', delivery_views.contractor_assign, name='contractor-assign'),
    path('project/contractors/<int:pk>/finish/', delivery_views.contractor_finish, name='contractor-finish'),
    path('project/<int:req_pk>/equipment/add/', delivery_views.equipment_edit, name='equipment-add'),
    path('project/equipment/<int:pk>/edit/', delivery_views.equipment_edit, name='equipment-edit'),
    path('project/equipment/<int:pk>/delete/', delivery_views.equipment_delete, name='equipment-delete'),
    path('project/<int:pk>/equipment/document/', delivery_views.equipment_document, name='equipment-document'),
    path('project/<int:req_pk>/insurance/add/', delivery_views.insurance_edit, name='insurance-add'),
    path('project/insurance/<int:pk>/edit/', delivery_views.insurance_edit, name='insurance-edit'),
    path('project/insurance/<int:pk>/delete/', delivery_views.insurance_delete, name='insurance-delete'),
    path('project/insurance/<int:pk>/file/', delivery_views.insurance_file, name='insurance-file'),
    path('manage/funnel/', admin_views.RequestFunnelView.as_view(), name='admin-funnel'),
    path('manage/leads/new/', admin_views.LeadCreateView.as_view(), name='admin-lead-create'),
    path('manage/<int:pk>/edit/', admin_views.LeadUpdateView.as_view(), name='admin-lead-edit'),
    path('manage/<int:pk>/notes/add/', admin_views.RequestNoteAddView.as_view(), name='admin-note-add'),
    path('manage/<int:pk>/funnel/advance/', admin_views.RequestFunnelAdvanceView.as_view(), name='admin-funnel-advance'),
    path('manage/<int:pk>/funnel/set/', admin_views.RequestFunnelSetView.as_view(), name='admin-funnel-set'),
    path('manage/dashboard/', admin_views.LeadDashboardView.as_view(), name='admin-dashboard'),
    path('manage/tracking/', admin_views.RequestTrackingView.as_view(), name='admin-tracking'),
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
    path('manage/tickets/new/', admin_views.TicketAdminCreateView.as_view(), name='admin-ticket-create'),
    path('manage/tickets/<int:pk>/', admin_views.TicketAdminDetailView.as_view(), name='admin-ticket-detail'),
    path('manage/tickets/<int:pk>/reply/', admin_views.TicketAdminReplyView.as_view(), name='admin-ticket-reply'),
    path('manage/tickets/<int:pk>/status/', admin_views.TicketAdminStatusView.as_view(), name='admin-ticket-status'),

    path('manage/<int:pk>/', admin_views.RequestAdminDetailView.as_view(), name='admin-detail'),
    path('manage/<int:pk>/offers/add/', admin_views.OfferAddView.as_view(), name='admin-offer-add'),
    path('manage/offers/<int:pk>/price/', admin_views.OfferPriceView.as_view(), name='admin-offer-price'),
    path('manage/offers/<int:pk>/toggle/', admin_views.OfferToggleView.as_view(), name='admin-offer-toggle'),
    path('manage/offers/<int:pk>/issue-contract/', admin_views.OfferIssueContractView.as_view(), name='admin-offer-issue-contract'),
    path('manage/<int:pk>/status/', admin_views.RequestStatusChangeView.as_view(), name='admin-status'),
    path('manage/<int:pk>/triage/', admin_views.RequestTriageView.as_view(), name='admin-triage'),
    path('manage/<int:pk>/marketing-refer/', admin_views.RequestMarketingReferView.as_view(), name='admin-marketing-refer'),
    path('manage/<int:pk>/refer-to-technical/', admin_views.RequestReferToTechnicalView.as_view(), name='admin-refer-to-technical'),
    path('manage/<int:pk>/hold/', admin_views.RequestHoldView.as_view(), name='admin-hold'),
    path('manage/<int:pk>/close-lost/', admin_views.RequestCloseLostView.as_view(), name='admin-close-lost'),
    path('manage/<int:pk>/refer-to-sales/', admin_views.RequestReferToSalesView.as_view(), name='admin-refer-to-sales'),
    path('manage/<int:pk>/close-sales/', admin_views.RequestCloseSalesView.as_view(), name='admin-close-sales'),
    path('manage/<int:pk>/lead-note/', admin_views.RequestLeadNoteView.as_view(), name='admin-lead-note'),
    path('manage/<int:pk>/toggle-edit/', admin_views.RequestToggleEditView.as_view(), name='admin-toggle-edit'),
    path('manage/<int:pk>/delete/', admin_views.RequestDeleteView.as_view(), name='admin-delete'),
    path('manage/<int:pk>/commission-plant/', admin_views.RequestCommissionPlantView.as_view(), name='admin-commission-plant'),

    # --- User panel ("درخواست‌های من") ---
    path('submit/', user_views.submit_request, name='submit'),
    path('login/', user_views.otp_login, name='otp-login'),
    path('verify/', user_views.verify, name='verify'),
    path('verify/resend/', user_views.resend_otp, name='resend-otp'),
    path('my-plant/', user_views.my_plant, name='my-plant'),
    path('mine/', user_views.MyRequestListView.as_view(), name='my-list'),
    path('mine/<int:pk>/', user_views.MyRequestDetailView.as_view(), name='my-detail'),
    path('mine/<int:pk>/edit/', user_views.MyRequestEditView.as_view(), name='my-edit'),
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
