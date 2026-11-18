from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.alerts.models import AlertEvent


from apps.plants.scoping import plant_scope_for_user as _plant_scope_for_user


@login_required
def report_center(request):
    plants = _plant_scope_for_user(request.user)
    rows = [(plant.name, f'{plant.capacity_kw} kW') for plant in plants]
    return render(request, 'reports/index.html', {'plants': plants, 'rows': rows})


@login_required
def export_pdf(request, plant_id):
    """Plant report as an A4 sheet; the browser saves it as PDF (print/sheet.html)."""
    from datetime import timedelta
    from django.utils import timezone
    from apps.core.localtime import day_start, local_day

    plants = _plant_scope_for_user(request.user)
    plant = get_object_or_404(plants.select_related('owner'), id=plant_id)
    today = timezone.localdate()
    since = day_start(today - timedelta(days=13))
    per_day = {today - timedelta(days=i): 0.0 for i in range(13, -1, -1)}
    for ts, kwh in plant.telemetry.filter(created_at__gte=since).values_list('created_at', 'energy_kwh'):
        day = local_day(ts)
        if day in per_day:
            per_day[day] += float(kwh or 0)
    peak = max(per_day.values()) or 1
    daily = [{'day': d, 'kwh': v, 'text': f'{v:,.0f}', 'pct': round(100 * v / peak)} for d, v in per_day.items()]
    latest = plant.telemetry.order_by('-created_at').first()
    alerts = AlertEvent.objects.filter(rule__plant=plant).select_related('rule').order_by('-created_at')
    modules = plant.modules.all()
    return render(request, 'reports/plant_print.html', {
        'plant': plant,
        'page_title': f'گزارش نیروگاه {plant.name}',
        'generated_at': timezone.now(),
        'inverters': plant.inverters.order_by('id'),
        'daily': daily,
        'energy_14d_text': f'{sum(per_day.values()):,.0f}',
        'latest': latest,
        'active_alerts': alerts.filter(acknowledged=False).count(),
        'recent_alerts': alerts[:8],
        'modules_total': modules.count(),
        'modules_hot': modules.filter(status='hot').count(),
        'modules_warn': modules.filter(status='warn').count(),
    })


@login_required
def export_excel(request, plant_id):
    """The customer's "تحلیل عملکرد" workbook (apps/reports/excel.py)."""
    import jdatetime
    from django.utils.http import content_disposition_header
    from .excel import build_performance_workbook

    plant = get_object_or_404(_plant_scope_for_user(request.user), id=plant_id)
    content = build_performance_workbook(plant)
    response = HttpResponse(content, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    name = f'تحلیل عملکرد {plant.name} {jdatetime.date.today().strftime("%Y-%m-%d")}.xlsx'
    response['Content-Disposition'] = content_disposition_header(True, name)
    return response


@login_required
def proposal(request):
    """Form -> filled 5-page proposal; the browser saves it as PDF."""
    from django.core.exceptions import PermissionDenied
    from django.http import JsonResponse
    from django.templatetags.static import static
    from django.utils.html import escape
    from django.utils.safestring import mark_safe
    from .forms import ProposalForm
    from .proposal import image_uri, render as render_proposal

    if not request.user.can_build_proposal:
        raise PermissionDenied
    # The form page posts with fetch and shows the result in place; a plain POST still works.
    ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    form = ProposalForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        d = {k: escape(v) if isinstance(v, str) else v for k, v in form.cleaned_data.items()}
        d['layout'] = image_uri(d['layout'])
        d['site'] = image_uri(d['site'])
        pages = render_proposal(d, static('img/pars-logo.webp'), static('img/proposal-cover.jpg'))
        return render(request, 'reports/proposal.html', {'pages': mark_safe(pages), 'title': d['customer'], 'embedded': ajax})
    if request.method == 'POST' and ajax:
        return JsonResponse({'errors': form.errors}, status=400)
    return render(request, 'reports/proposal_form.html', {'form': form, 'title': 'پیشنهاد تجاری اولیه'})
