"""Data-access layer for the requests module.

Views and services go through these helpers instead of querying models
directly, so access scoping lives in exactly one place.
"""
from __future__ import annotations

import re

from django.db.models import Q

from apps.core.localtime import before_end_of, on_or_after

from .models import Request, RequestOffer, RequestPayment


def is_management(user) -> bool:
    """Admins/superusers who oversee every department (NOT customers/owners)."""
    return bool(
        getattr(user, 'is_superuser', False)
        or getattr(user, 'role', '') == 'admin'
    )


def is_marketing(user) -> bool:
    return getattr(user, 'role', '') == 'marketing'


def is_sales(user) -> bool:
    return getattr(user, 'role', '') == 'sales'


def is_technical(user) -> bool:
    return getattr(user, 'role', '') == 'technical'


def is_operations(user) -> bool:
    return getattr(user, 'role', '') == 'operations'


def is_financial(user) -> bool:
    """Contracts, invoices and settlement.

    Reads the commercial tail of the pipeline. Deliberately *not* an owner of
    any stage: finance never moves a request forward, so it appears in the
    read predicates and not in the ones that gate stage transitions.
    """
    return getattr(user, 'role', '') == 'financial'


def is_senior_marketing(user) -> bool:
    """A marketer granted sight of every lead, whoever captured it."""
    return bool(is_marketing(user) and user.has_permission_code('leads.view_all'))


def is_identity_restricted(user) -> bool:
    """Pure technical staff must not see customer identity or financial fields."""
    return bool(is_technical(user) and not is_management(user))


def is_request_staff(user) -> bool:
    """Any staff role that may open the requests panel."""
    return bool(
        is_management(user)
        or is_marketing(user)
        or is_sales(user)
        or is_technical(user)
        or is_operations(user)
        or is_financial(user)
        or (hasattr(user, 'has_permission_code') and user.has_permission_code('requests.manage'))
    )


def is_request_manager(user) -> bool:
    """Commercial / oversight roles (identity allowed)."""
    return bool(
        is_management(user)
        or is_marketing(user)
        or is_sales(user)
        or is_operations(user)
        or is_financial(user)
        or (hasattr(user, 'has_permission_code') and user.has_permission_code('requests.manage'))
    )


def can_search_identity(user) -> bool:
    """Who may search by mobile / full name."""
    return bool(is_management(user) or is_marketing(user) or is_sales(user)
                or is_operations(user) or is_financial(user))


def scope_requests_by_department(user, qs):
    """Restrict a request queryset to the department(s) a staff user may see."""
    if is_management(user) or is_operations(user) or is_senior_marketing(user):
        return qs
    if is_marketing(user):
        # Website leads are shared across the marketing team as before. An
        # exhibition lead belongs to whoever was standing at the stand, so the
        # other marketers' QR captures are filtered out.
        #
        # A marketer also keeps sight of the leads they personally captured
        # after referring them on. Scoping purely by department meant that the
        # moment they did their job and handed a lead to sales, it vanished —
        # they could not follow what became of it or add what they had learned.
        mine = Q(exhibition__marketer=user)
        return qs.filter(
            Q(department=Request.Department.MARKETING) | mine
        ).exclude(Q(exhibition__isnull=False) & ~mine)
    if is_technical(user):
        # Technical sees technical queue and later stages for commissioning.
        return qs.filter(department__in=(
            Request.Department.TECHNICAL,
            Request.Department.SALES,
            Request.Department.DONE,
        ))
    if is_sales(user):
        # Sales watches leads from the moment they land, not only once
        # marketing has handed them over — a new lead is a sales opportunity
        # straight away and waiting for a referral loses time.
        return qs.filter(department__in=(
            Request.Department.MARKETING,
            Request.Department.SALES,
            Request.Department.DONE))
    if is_financial(user):
        # Money only exists from negotiation onward: an offer is chosen, a
        # contract is issued, a payment settles. Earlier stages have nothing
        # for finance to look at, so they are not shown.
        return qs.filter(department__in=(
            Request.Department.SALES,
            Request.Department.DONE))
    return qs.none()


def scope_related_by_department(user, qs, field='request'):
    if is_management(user) or is_operations(user):
        return qs
    if is_marketing(user):
        return qs.filter(**{f'{field}__department': Request.Department.MARKETING})
    if is_technical(user):
        return qs.filter(**{f'{field}__department__in': (
            Request.Department.TECHNICAL,
            Request.Department.SALES,
            Request.Department.DONE,
        )})
    if is_sales(user):
        return qs.filter(**{f'{field}__department__in': (
            Request.Department.MARKETING,
            Request.Department.SALES,
            Request.Department.DONE)})
    if is_financial(user):
        return qs.filter(**{f'{field}__department__in': (
            Request.Department.SALES,
            Request.Department.DONE)})
    return qs.none()


def scope_tickets_by_department(user, qs):
    """Each staff role only sees its own inbox + tickets it opened.

    Management (admin) alone sees the full queue.
    """
    from django.db.models import Q

    from .models import Ticket

    if is_management(user):
        return qs
    mine = Q(user=user)
    if is_technical(user):
        return qs.filter(mine | Q(department=Ticket.Department.TECHNICAL))
    if is_sales(user):
        return qs.filter(mine | Q(department=Ticket.Department.SALES))
    if is_marketing(user):
        return qs.filter(mine | Q(department=Ticket.Department.MARKETING))
    if is_operations(user):
        return qs.filter(mine | Q(department=Ticket.Department.OPERATIONS))
    return qs.none()


def can_create_lead(user) -> bool:
    return bool(is_management(user) or is_operations(user) or is_marketing(user) or is_sales(user))


def owns_current_stage(user, req) -> bool:
    """The team holding the case now, plus management and operations."""
    if is_management(user) or is_operations(user):
        return True
    dept = Request.Department
    return ((is_marketing(user) and req.department == dept.MARKETING)
            or (is_sales(user) and req.department == dept.SALES)
            or (is_technical(user) and req.department == dept.TECHNICAL))


def can_edit_lead(user, req) -> bool:
    # The technical team may not see who the customer is, so it never edits them.
    return owns_current_stage(user, req) and not is_identity_restricted(user)


def overdue_requests(qs):
    """Open cases that have sat in one stage longer than the follow-up limit."""
    from datetime import timedelta

    from django.utils import timezone

    from .services import lifecycle

    dept, status = Request.Department, Request.Status
    return qs.filter(
        department__in=(dept.MARKETING, dept.SALES, dept.TECHNICAL),
        stage_entered_at__lt=timezone.now() - timedelta(hours=lifecycle.STAGE_SLA_HOURS),
    ).exclude(status__in=(status.CLOSED, status.CANCELLED, status.PAID))


def requests_for_user(user):
    qs = Request.objects.select_related('user')
    if is_request_manager(user) or is_technical(user):
        return qs
    return qs.filter(user=user)


def get_user_request(user, request_id):
    return requests_for_user(user).filter(pk=request_id).first()


def _as_list(value):
    if value in (None, ''):
        return []
    values = value if isinstance(value, (list, tuple)) else [value]
    return [v for v in values if v not in (None, '')]


def _match(column, value):
    """One value filters with `=`; several ticked boxes filter with `IN`."""
    if isinstance(value, (list, tuple)):
        values = [v for v in value if v not in (None, '')]
        return {f'{column}__in': values} if len(values) != 1 else {column: values[0]}
    return {column: value}


def filter_requests(
    *,
    status=None,
    province=None,
    city=None,
    department=None,
    funnel_stage=None,
    sales_phase=None,
    priority=None,
    request_type=None,
    partnership_type=None,
    install_location=None,
    lead_source=None,
    campaign_name=None,
    sales_assignee=None,
    technical_status=None,
    crm_transferred=None,
    date_from=None,
    date_to=None,
    updated_from=None,
    updated_to=None,
    q=None,
    identity_search: bool = True,
):
    """Admin list filtering + optional free-text search."""
    qs = Request.objects.select_related(
        'user', 'sales_completed_by', 'technical_completed_by',
        'sales_assignee', 'marketing_reviewed_by', 'exhibition',
    ).all()
    if status:
        qs = qs.filter(**_match('status', status))
    if province:
        qs = qs.filter(**_match('province', province))
    if city:
        qs = qs.filter(**_match('city', city))
    if department:
        qs = qs.filter(**_match('department', department))
    if funnel_stage:
        qs = qs.filter(**_match('funnel_stage', funnel_stage))
    if sales_phase:
        qs = qs.filter(sales_phase=sales_phase)
    if priority:
        qs = qs.filter(**_match('priority', priority))
    if request_type:
        qs = qs.filter(**_match('request_type', request_type))
    if partnership_type:
        qs = qs.filter(**_match('partnership_type', partnership_type))
    if install_location:
        qs = qs.filter(**_match('install_location', install_location))
    if lead_source:
        qs = qs.filter(**_match('lead_source', lead_source))
    if campaign_name:
        qs = qs.filter(**_match('campaign_name', campaign_name))
    if sales_assignee:
        qs = qs.filter(**_match('sales_assignee_id', sales_assignee))
    tech = set(_as_list(technical_status))
    if tech and tech != {'pending', 'done'}:
        tech_q = Q()
        if 'pending' in tech:
            tech_q |= Q(department=Request.Department.TECHNICAL, technical_completed_at__isnull=True)
        if 'done' in tech:
            tech_q |= Q(technical_completed_at__isnull=False)
        qs = qs.filter(tech_q)
    crm = {str(v).lower() for v in _as_list(crm_transferred)}
    crm = {'1' if v in ('1', 'true') else '0' if v in ('0', 'false') else v for v in crm}
    if crm == {'1'}:
        qs = qs.filter(crm_transferred=True)
    elif crm == {'0'}:
        qs = qs.filter(crm_transferred=False)
    # Datetime ranges, not __date: the production DB has no time-zone tables,
    # so __date there matched nothing at all (apps.core.localtime).
    if date_from:
        qs = qs.filter(**on_or_after('created_at', date_from))
    if date_to:
        qs = qs.filter(**before_end_of('created_at', date_to))
    if updated_from:
        qs = qs.filter(**on_or_after('updated_at', updated_from))
    if updated_to:
        qs = qs.filter(**before_end_of('updated_at', updated_to))
    # Several search words are allowed, split by comma: a request matching
    # any one of them is shown.
    terms = [t.strip() for t in re.split(r'[,،]', ' , '.join(map(str, _as_list(q)))) if t.strip()]
    if terms:
        clauses = Q()
        for term in terms:
            if term.isdigit():
                clauses |= Q(pk=int(term))
            clauses |= Q(province__icontains=term) | Q(city__icontains=term) | Q(install_address__icontains=term)
            if identity_search:
                clauses |= (Q(full_name__icontains=term) | Q(mobile__icontains=term)
                            | Q(exhibition__company__icontains=term))
        qs = qs.filter(clauses)
    return qs


def offers_for_request(request) -> list[RequestOffer]:
    return list(request.offers.all())


def offer_count(request) -> int:
    return request.offers.count()


def payment_by_token(token):
    return (
        RequestPayment.objects
        .select_related('request', 'offer')
        .filter(token=token)
        .first()
    )


def payments_for_request(request):
    return request.payments.select_related('offer').all()


def messages_for_request(request):
    return request.message_logs.all()
