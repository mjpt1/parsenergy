import json

from django import template

register = template.Library()


@register.filter
def get_field(form, key):
    """`form[key]` for a runtime key — returns None instead of raising when the
    builder references a field the form doesn't declare (e.g. RequestEditForm
    drops mobile/national_id/accepted_terms)."""
    try:
        return form[key]
    except KeyError:
        return None


@register.filter
def as_json(value):
    """Serialize a condition list for the wizard's data-when attribute."""
    return json.dumps(value or [], ensure_ascii=False)


@register.inclusion_tag('includes/location_select.html')
def location_select():
    """The province → city lists and the script that drives them."""
    from apps.requests.iran_locations import CITIES
    return {'cities': CITIES}
