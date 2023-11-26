from appdaemon.plugins.hass.hassapi import Hass
from room_control import RoomController


class Door(Hass):
    async def initialize(self):
        app: RoomController = await self.get_app(self.args['app'])
        await self.listen_state(app.activate_all_off, entity_id=self.args['door'], new='on', cause='door open')
