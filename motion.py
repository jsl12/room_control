import re
from datetime import timedelta

from appdaemon.entity import Entity
from appdaemon.plugins.hass.hassapi import Hass
from room_control import RoomController

from appdaemon import utils


class Motion(Hass):
    @property
    def sensor(self) -> Entity:
        return self.get_entity(self.args['sensor'])

    @property
    def sensor_state(self) -> bool:
        return self.sensor.state == 'on'

    @property
    def ref_entity(self) -> Entity:
        return self.get_entity(self.args['ref_entity'])

    @property
    async def ref_entity_state(self) -> bool:
        return (await self.ref_entity.get_state()) == 'on'

    async def initialize(self):
        self.app: RoomController = await self.get_app(self.args['app'])
        self.log(f'Connected to app {self.app.name}')

        base_kwargs = dict(
            entity_id=self.ref_entity.entity_id,
            immediate=True, # avoids needing to sync the state
        )
        # don't need to await these because they'll already get turned into a task by the utils.sync_wrapper decorator
        self.listen_state(**base_kwargs, attribute='brightness', callback=self.callback_light_on)
        self.listen_state(**base_kwargs, new='off', callback=self.callback_light_off)

    async def listen_motion_on(self):
        """Sets up the motion on callback to activate the room
        """
        await self.cancel_motion_callback()
        await self.listen_state(
            callback=self.app.activate_all_off,
            entity_id=self.sensor.entity_id,
            new='on',
            oneshot=True,
            cause='motion on'
        )
        self.log(f'Waiting for motion on {self.sensor.friendly_name}')

    async def listen_motion_off(self, duration: timedelta):
        """Sets up the motion off callback to deactivate the room
        """
        await self.cancel_motion_callback()
        await self.listen_state(
            callback=self.app.deactivate,
            entity_id=self.sensor.entity_id,
            new='off',
            duration=duration.total_seconds(),
            oneshot=True,
            cause='motion off'
        )
        self.log(f'Waiting for motion to stop on {self.sensor.friendly_name} for {duration}')

    @utils.sync_wrapper
    async def callback_light_on(self, entity=None, attribute=None, old=None, new=None, kwargs=None):
        """Called when the light turns on
        """
        if new is not None:
            self.log(f'{entity} turned on')
            duration = await self.app.off_duration()
            await self.listen_motion_off(duration)

    @utils.sync_wrapper
    async def callback_light_off(self, entity=None, attribute=None, old=None, new=None, kwargs=None):
        """Called when the light turns off
        """
        self.log(f'{entity} turned off')
        await self.listen_motion_on()

    async def get_app_callbacks(self, name: str = None):
        """Gets all the callbacks associated with the app
        """
        name = name or self.name
        callbacks = {
            handle: info
            for app_name, callbacks in (await self.get_callback_entries()).items()
            for handle, info in callbacks.items()
            if app_name == name
        }
        return callbacks
                
    async def get_sensor_callbacks(self):
        return {
            handle: info
            for handle, info in (await self.get_app_callbacks()).items()
            if info['entity'] == self.sensor.entity_id
        }

    async def cancel_motion_callback(self):
        callbacks = await self.get_sensor_callbacks()
        self.log(f'Found {len(callbacks)} callbacks for {self.sensor.entity_id}')
        for handle, info in callbacks.items():
            entity = info["entity"]
            kwargs = info['kwargs']
            if (m := re.match('new=(?P<new>.*?)\s', kwargs)) is not None:
                new = m.group('new')
                await self.cancel_listen_state(handle)
                self.log(f'cancelled callback for sensor {entity} turning {new}')
