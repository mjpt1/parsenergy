from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone


@dataclass(frozen=True)
class RangeWindow:
    start: datetime
    end: datetime


def last_24_hours() -> RangeWindow:
    end = timezone.now()
    return RangeWindow(start=end - timedelta(hours=24), end=end)
