from appdaemon.plugins.hass.hassapi import Hass
from room_control import RoomController


class Door(Hass):
    async def initialize(self):
        await self.listen_state(self.door_open, entity_id=self.args['door'], new='on')
    
    async def door_open(self, entity, attribute, old, new, kwargs):
        app: RoomController = await self.get_app(self.args['app'])
        await app.activate_all_off()
