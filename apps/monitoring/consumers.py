from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer


class TelemetryConsumer(AsyncJsonWebsocketConsumer):
    """Streams live telemetry, but only for plants the connected user may access.

    Each plant broadcasts to its own group (``telemetry_plant_<id>``); on connect
    we subscribe the socket to the groups for the user's accessible plants only.
    Unauthenticated sockets are rejected.
    """

    async def connect(self):
        user = self.scope.get('user')
        if user is None or not user.is_authenticated:
            await self.close(code=4401)
            return
        self.group_names = await self._groups_for_user(user)
        for group in self.group_names:
            await self.channel_layer.group_add(group, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        for group in getattr(self, 'group_names', []):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def telemetry_update(self, event):
        await self.send_json(event['data'])

    @database_sync_to_async
    def _groups_for_user(self, user):
        from apps.plants.scoping import plant_scope_for_user
        plant_ids = plant_scope_for_user(user).values_list('id', flat=True)
        return [f'telemetry_plant_{plant_id}' for plant_id in plant_ids]
