from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from .models import VPP, VPPMember, DispatchSchedule
from .forms import VPPForm, VPPMemberForm, DispatchScheduleForm


class VPPListView(LoginRequiredMixin, ListView):
    model = VPP
    template_name = 'vpp/list.html'

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'role', '') == 'admin':
            return VPP.objects.all().order_by('-created_at')
        return VPP.objects.filter(owner=user).order_by('-created_at')


class VPPCreateView(LoginRequiredMixin, CreateView):
    model = VPP
    form_class = VPPForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('vpp:list')

    def form_valid(self, form):
        if not form.instance.owner_id:
            form.instance.owner = self.request.user
        messages.success(self.request, _('VPP با موفقیت ایجاد شد.'))
        return super().form_valid(form)


class VPPUpdateView(LoginRequiredMixin, UpdateView):
    model = VPP
    form_class = VPPForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('vpp:list')

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'role', '') == 'admin':
            return VPP.objects.all()
        return VPP.objects.filter(owner=user)


class VPPDeleteView(LoginRequiredMixin, DeleteView):
    model = VPP
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('vpp:list')

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'role', '') == 'admin':
            return VPP.objects.all()
        return VPP.objects.filter(owner=user)


class VPPMemberListView(LoginRequiredMixin, ListView):
    model = VPPMember
    template_name = 'vpp/members_list.html'

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'role', '') == 'admin':
            return VPPMember.objects.select_related('vpp', 'plant').all().order_by('-id')
        return VPPMember.objects.select_related('vpp', 'plant').filter(vpp__owner=user).order_by('-id')


class VPPMemberCreateView(LoginRequiredMixin, CreateView):
    model = VPPMember
    form_class = VPPMemberForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('vpp:members')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class VPPMemberUpdateView(LoginRequiredMixin, UpdateView):
    model = VPPMember
    form_class = VPPMemberForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('vpp:members')

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'role', '') == 'admin':
            return VPPMember.objects.select_related('vpp', 'plant').all()
        return VPPMember.objects.select_related('vpp', 'plant').filter(vpp__owner=user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class VPPMemberDeleteView(LoginRequiredMixin, DeleteView):
    model = VPPMember
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('vpp:members')

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'role', '') == 'admin':
            return VPPMember.objects.select_related('vpp', 'plant').all()
        return VPPMember.objects.select_related('vpp', 'plant').filter(vpp__owner=user)


class DispatchScheduleListView(LoginRequiredMixin, ListView):
    model = DispatchSchedule
    template_name = 'vpp/schedules_list.html'

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'role', '') == 'admin':
            return DispatchSchedule.objects.select_related('vpp').all().order_by('-start_time')
        return DispatchSchedule.objects.select_related('vpp').filter(vpp__owner=user).order_by('-start_time')


class DispatchScheduleCreateView(LoginRequiredMixin, CreateView):
    model = DispatchSchedule
    form_class = DispatchScheduleForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('vpp:schedules')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class DispatchScheduleUpdateView(LoginRequiredMixin, UpdateView):
    model = DispatchSchedule
    form_class = DispatchScheduleForm
    template_name = 'crud/form.html'
    success_url = reverse_lazy('vpp:schedules')

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'role', '') == 'admin':
            return DispatchSchedule.objects.select_related('vpp').all()
        return DispatchSchedule.objects.select_related('vpp').filter(vpp__owner=user)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class DispatchScheduleDeleteView(LoginRequiredMixin, DeleteView):
    model = DispatchSchedule
    template_name = 'crud/confirm_delete.html'
    success_url = reverse_lazy('vpp:schedules')

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or getattr(user, 'role', '') == 'admin':
            return DispatchSchedule.objects.select_related('vpp').all()
        return DispatchSchedule.objects.select_related('vpp').filter(vpp__owner=user)
