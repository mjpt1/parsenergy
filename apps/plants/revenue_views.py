"""Income pages, and the roof sections that describe how a plant is really built."""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, ListView, TemplateView, UpdateView

from apps.core.services import write_audit_log

from .forms import PlantSectionForm
from .monitor import build_monitor
from .screen import build_screen
from .models import Inverter, Plant, PlantBill, PlantSection, PlantTariff
from .revenue import (
    build_revenue, bill_groups, custom_period, jalali_text, number_text, parse_jalali, plant_rates,
    revenue_plants, to_latin_digits,
)

MAX_RATE_RIAL = Decimal('1000000000')


def _revenue_url(plant_id):
    return f'{reverse("plants:revenue")}?plant={plant_id}'


class RevenueView(LoginRequiredMixin, TemplateView):
    template_name = 'plants/revenue.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        params = self.request.GET
        plants = list(revenue_plants(user).order_by('name'))
        wanted = params.get('plant', '')
        plant = next((p for p in plants if str(p.pk) == wanted), plants[0] if plants else None)
        ctx.update({
            'page_title': 'درآمد نیروگاه',
            'base_template': _shell(user),
            'portal_tab': 'dashboard',
            'plants': plants,
            'plant': plant,
            'plant_tab': 'revenue',
            'can_set_rate': user.is_management(),
        })
        if plant is None:
            return ctx
        ctx['revenue'] = build_revenue(plant)
        ctx['rates'] = [{'obj': r, 'from_text': jalali_text(r.valid_from)} for r in reversed(plant_rates(plant))]
        ctx['today_text'] = jalali_text(timezone.localdate())
        first, last = params.get('from', '').strip(), params.get('to', '').strip()
        ctx['range_from'], ctx['range_to'] = first, last
        if first or last:
            try:
                start, end = parse_jalali(first), parse_jalali(last)
                if start > end:
                    raise ValueError('reversed')
                ctx['custom'] = custom_period(plant, start, end)
            except ValueError:
                ctx['range_error'] = 'تاریخ‌ها را به شکل ۱۴۰۵/۰۸/۰۱ وارد کنید و تاریخ شروع از پایان جلوتر نباشد.'
        return ctx


class RevenueDataView(LoginRequiredMixin, View):
    def get(self, request, pk):
        plant = get_object_or_404(revenue_plants(request.user), pk=pk)
        data = build_revenue(plant)
        for period in data['periods']:
            period.pop('toman')
        return JsonResponse(data)


class ManagementOnlyMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_management():
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class RevenueRateSaveView(ManagementOnlyMixin, View):
    def post(self, request, pk):
        plant = get_object_or_404(Plant, pk=pk)
        raw = to_latin_digits(request.POST.get('rate')).replace(',', '').replace('٬', '')
        try:
            rate = Decimal(raw)
            day = parse_jalali(request.POST.get('valid_from'))
            if not 0 < rate <= MAX_RATE_RIAL:
                raise ValueError('range')
        except (InvalidOperation, ValueError):
            messages.error(request, 'نرخ باید عددی مثبت به ریال و تاریخ به شکل ۱۴۰۵/۰۸/۰۱ باشد.')
            return redirect(_revenue_url(plant.pk))
        PlantTariff.objects.update_or_create(
            plant=plant, valid_from=day, defaults={'rate_rial_per_kwh': rate, 'created_by': request.user})
        write_audit_log(actor=request.user, action='plant.tariff_saved', target_type='plant',
                        target_id=str(plant.pk), metadata={'rate_rial': str(rate), 'valid_from': str(day)})
        messages.success(request, 'نرخ خرید برق ثبت شد.')
        return redirect(_revenue_url(plant.pk))


class RevenueRateDeleteView(ManagementOnlyMixin, View):
    def post(self, request, pk):
        tariff = get_object_or_404(PlantTariff, pk=pk)
        plant_id = tariff.plant_id
        write_audit_log(actor=request.user, action='plant.tariff_deleted', target_type='plant',
                        target_id=str(plant_id),
                        metadata={'rate_rial': str(tariff.rate_rial_per_kwh), 'valid_from': str(tariff.valid_from)})
        tariff.delete()
        messages.success(request, 'نرخ حذف شد.')
        return redirect(_revenue_url(plant_id))


def _shell(user):
    return 'base_portal.html' if user.role in ('owner', 'customer') else 'base.html'


def _bills_url(plant_id):
    return f'{reverse("plants:bills")}?plant={plant_id}'


def _amount(raw, *, required=True):
    text = to_latin_digits(raw).replace(',', '').replace('٬', '')
    if not text and not required:
        return None
    return Decimal(text)


class BillsView(LoginRequiredMixin, TemplateView):
    template_name = 'plants/bills.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user, params = self.request.user, self.request.GET
        plants = list(revenue_plants(user).order_by('name'))
        wanted = params.get('plant', '')
        plant = next((p for p in plants if str(p.pk) == wanted), plants[0] if plants else None)
        mode = params.get('mode') if params.get('mode') in ('bill', 'month', 'year') else 'bill'
        first, last = params.get('from', '').strip(), params.get('to', '').strip()
        ctx.update({'page_title': 'صورتحساب نیروگاه', 'base_template': _shell(user), 'portal_tab': 'dashboard',
                    'plants': plants, 'plant': plant, 'plant_tab': 'bills', 'mode': mode, 'can_manage': user.is_management(),
                    'range_from': first, 'range_to': last, 'today_text': jalali_text(timezone.localdate())})
        if plant is None:
            return ctx
        bills = PlantBill.objects.filter(plant=plant)
        ctx['latest'] = bills.first()
        try:
            if first:
                bills = bills.filter(period_end__gt=parse_jalali(first))
            if last:
                bills = bills.filter(period_start__lte=parse_jalali(last))
        except ValueError:
            ctx['range_error'] = 'تاریخ‌ها را به شکل ۱۴۰۵/۰۸/۰۱ وارد کنید.'
        rows = list(bills)
        ctx['groups'] = bill_groups(rows, mode)
        ctx['bills'] = [{
            'obj': bill, 'from_text': jalali_text(bill.period_start), 'to_text': jalali_text(bill.period_end),
            'energy_text': number_text(bill.energy_kwh), 'income_text': number_text(bill.income_rial),
            'balance_text': number_text(bill.balance_rial), 'net_text': number_text(bill.net_rial),
        } for bill in rows]
        return ctx


class MonitorView(LoginRequiredMixin, TemplateView):
    template_name = 'plants/monitor.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        plants = list(revenue_plants(user).order_by('name'))
        wanted = self.request.GET.get('plant', '')
        plant = next((p for p in plants if str(p.pk) == wanted), plants[0] if plants else None)
        ctx.update({'page_title': 'پایش کامل نیروگاه', 'base_template': _shell(user), 'portal_tab': 'dashboard',
                    'plants': plants, 'plant': plant, 'plant_tab': 'monitor'})
        return ctx


class MonitorDataView(LoginRequiredMixin, View):
    def get(self, request, pk):
        plant = get_object_or_404(revenue_plants(request.user), pk=pk)
        return JsonResponse(build_monitor(plant, request.GET.get('range', '1')))


class ScreenView(LoginRequiredMixin, TemplateView):
    template_name = 'plants/screen.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        plants = list(revenue_plants(user).order_by('name'))
        wanted = self.request.GET.get('plant', '')
        plant = next((p for p in plants if str(p.pk) == wanted), plants[0] if plants else None)
        ctx.update({'page_title': 'نمای زندهٔ نیروگاه', 'base_template': _shell(user), 'portal_tab': 'dashboard',
                    'plants': plants, 'plant': plant, 'plant_tab': 'screen'})
        return ctx


class ScreenDataView(LoginRequiredMixin, View):
    def get(self, request, pk):
        return JsonResponse(build_screen(get_object_or_404(revenue_plants(request.user), pk=pk)))


class BillSaveView(ManagementOnlyMixin, View):
    def post(self, request, pk):
        plant = get_object_or_404(Plant, pk=pk)
        data = request.POST
        try:
            start, end = parse_jalali(data.get('period_start')), parse_jalali(data.get('period_end'))
            values = {
                'energy_kwh': _amount(data.get('energy_kwh')),
                'benchmark_kwh': _amount(data.get('benchmark_kwh'), required=False),
                'income_rial': _amount(data.get('income_rial')),
                'balance_rial': _amount(data.get('balance_rial'), required=False) or Decimal('0'),
                'net_rial': _amount(data.get('net_rial')),
            }
            if start >= end or values['energy_kwh'] < 0 or values['income_rial'] < 0:
                raise ValueError('range')
        except (InvalidOperation, ValueError):
            messages.error(request, 'تاریخ‌ها و مبلغ‌ها را بررسی کنید؛ تاریخ پایان باید بعد از شروع باشد.')
            return redirect(_bills_url(plant.pk))
        PlantBill.objects.update_or_create(plant=plant, period_end=end, defaults={
            **values, 'period_start': start, 'created_by': request.user,
            'customer_name': data.get('customer_name', '').strip()[:160],
            'file_number': to_latin_digits(data.get('file_number'))[:40]})
        write_audit_log(actor=request.user, action='plant.bill_saved', target_type='plant', target_id=str(plant.pk),
                        metadata={'period_end': str(end), 'energy_kwh': str(values['energy_kwh'])})
        messages.success(request, 'صورتحساب ثبت شد.')
        return redirect(_bills_url(plant.pk))


class BillDeleteView(ManagementOnlyMixin, View):
    def post(self, request, pk):
        bill = get_object_or_404(PlantBill, pk=pk)
        plant_id = bill.plant_id
        write_audit_log(actor=request.user, action='plant.bill_deleted', target_type='plant', target_id=str(plant_id),
                        metadata={'period_end': str(bill.period_end), 'energy_kwh': str(bill.energy_kwh)})
        bill.delete()
        messages.success(request, 'صورتحساب حذف شد.')
        return redirect(_bills_url(plant_id))


class InverterDetailView(LoginRequiredMixin, TemplateView):
    template_name = 'plants/inverter_detail.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        inverter = get_object_or_404(Inverter.objects.select_related('plant'), pk=kwargs['pk'],
                                     plant__in=revenue_plants(user))
        data = inverter.latest_data or {}
        ctx.update({'page_title': 'جزئیات اینورتر', 'base_template': _shell(user), 'portal_tab': 'dashboard',
                    'inverter': inverter, 'data': data, 'channel_groups': [
                        {'title': 'ورودی‌های MPPT', 'rows': data.get('mppt') or []},
                        {'title': 'رشته‌های پنل (PV)', 'rows': data.get('pv') or []}]})
        return ctx


class SectionAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return user.is_management() or user.role in ('technical', 'operations')


class SectionListView(SectionAccessMixin, ListView):
    template_name = 'plants/list_section.html'

    def get_queryset(self):
        return PlantSection.objects.select_related('plant', 'inverter').order_by('plant__name', 'sort_order', 'id')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        summary = {}
        for section in ctx['object_list']:
            row = summary.setdefault(section.plant_id, {
                'plant': section.plant, 'designed': Decimal('0'), 'connected': Decimal('0')})
            row['designed'] += section.kwp
            if section.inverter_id:
                row['connected'] += section.kwp
        ctx['plant_summary'] = list(summary.values())
        return ctx


class SectionCreateView(SectionAccessMixin, CreateView):
    model = PlantSection
    form_class = PlantSectionForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:sections')


class SectionUpdateView(SectionAccessMixin, UpdateView):
    model = PlantSection
    form_class = PlantSectionForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('plants:sections')


class SectionDeleteView(SectionAccessMixin, DeleteView):
    model = PlantSection
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('plants:sections')
