from typing import Any
from typing import Optional
from .models import AuditLog


def write_audit_log(*, actor, action: str, target_type: str, target_id: str = '', metadata: Optional[dict[str, Any]] = None, ip_address: Optional[str] = None):
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata or {},
        ip_address=ip_address,
    )
