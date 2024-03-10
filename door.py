from appdaemon.plugins.hass.hassapi import Hass
from console import setup_component_logging

from room_control import RoomController


class Door(Hass):
    async def initialize(self):
        setup_component_logging(self)
        self.app: RoomController = await self.get_app(self.args['app'])
        self.log(f'Connected to AD app [room]{self.app.name}[/]', level='DEBUG')

        await self.listen_state(self.app.activate_all_off, entity_id=self.args['door'], new='on', cause='door open')
        
