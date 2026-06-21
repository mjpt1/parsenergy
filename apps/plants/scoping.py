from django.db.models import Q

from .models import Plant, PlantMembership


def plant_scope_for_user(user):
    """Plants a user may access: all for admins/superusers, else owned plants
    plus plants where the user has an active membership."""
    if user.is_superuser or getattr(user, 'role', '') == 'admin':
        return Plant.objects.all()
    member_ids = PlantMembership.objects.filter(user=user, active=True).values_list('plant_id', flat=True)
    return Plant.objects.filter(Q(owner=user) | Q(id__in=member_ids)).distinct()
