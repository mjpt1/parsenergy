from django.contrib import admin
from .models import (
    SystemParameter,
    SecuritySetting,
    AuditLog,
    ServerHealthMetric,
    DatabaseBackup,
    APIConnection,
    ProtocolAdapter,
)

admin.site.register(SystemParameter)
admin.site.register(SecuritySetting)
admin.site.register(AuditLog)
admin.site.register(ServerHealthMetric)
admin.site.register(DatabaseBackup)
admin.site.register(APIConnection)
admin.site.register(ProtocolAdapter)
