from django.db.models import Q

from .models import Plant, PlantMembership


def plant_scope_for_user(user):
    """Plants a user may access: all for admins/superusers/technical/operations,
    else owned plants plus plants where the user has an active membership."""
    role = getattr(user, 'role', '')
    if user.is_superuser or role in ('admin', 'technical', 'operations'):
        return Plant.objects.all()
    member_ids = PlantMembership.objects.filter(user=user, active=True).values_list('plant_id', flat=True)
    return Plant.objects.filter(Q(owner=user) | Q(id__in=member_ids)).distinct()
