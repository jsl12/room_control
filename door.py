from appdaemon.plugins.hass.hassapi import Hass
from room_control import RoomController


class DoorControl(Hass):
    def initialize(self):
        self.listen_state(self.door_open, entity_id=self.args['door'], new='on')
    
    def door_open(self, entity, attribute, old, new, kwargs):
        app: RoomController = self.get_app(self.args['app'])
        app.activate_all_off()