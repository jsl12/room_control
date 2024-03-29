import asyncio
from datetime import timedelta
import re

from appdaemon.entity import Entity
from appdaemon.plugins.hass.hassapi import Hass
from room_control import RoomController


class CustomEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    def get_event_loop(self):
        try:
            # Try to get the current event loop
            loop = super().get_event_loop()
        except RuntimeError as ex:
            if "There is no current event loop" in str(ex):
                # If there's no current loop, create a new one and set it
                loop = self.new_event_loop()
                self.set_event_loop(loop)
            else:
                raise
        return loop

# Set the custom event loop policy
asyncio.set_event_loop_policy(CustomEventLoopPolicy())

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
    def ref_entity_state(self) -> bool:
        return self.ref_entity.get_state() == 'on'

    def initialize(self):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()

        self.app: RoomController = loop.run_until_complete(self.get_app(self.args['app']))
        self.log(f'Connected to app {self.app.name}')

        self.listen_state(self.callback_light_on, self.ref_entity.entity_id, new='on')
        self.listen_state(self.callback_light_off, self.ref_entity.entity_id, new='off')

        loop.run_until_complete(self.sync_state())

    async def sync_state(self):
        """Synchronizes the callbacks with the state of the light.

        Essentially mimics the `state_change` callback based on the current state of the light.
        """
        if self.ref_entity_state:
            await self.callback_light_on()
        else:
            await self.callback_light_off()

    async def listen_motion_on(self):
        """Sets up the motion on callback to activate the room
        """
        self.log(f'Waiting for motion on {self.sensor.friendly_name}')
        self.motion_on_handle = await self.listen_state(
            callback=self.app.activate_all_off,
            entity_id=self.sensor.entity_id,
            new='on',
            oneshot=True,
            cause='motion on'
        )

    async def listen_motion_off(self, duration: timedelta):
        """Sets up the motion off callback to deactivate the room
        """
        self.log(f'Waiting for motion to stop on {self.sensor.friendly_name}')
        self.motion_off_handle = await self.listen_state(
            callback=self.app.deactivate,
            entity_id=self.sensor.entity_id,
            new='off',
            duration=duration.total_seconds(),
            oneshot=True,
            cause='motion off'
        )

    async def callback_light_on(self, entity=None, attribute=None, old=None, new=None, kwargs=None):
        """Called when the light turns on
        """
        self.log('Light on callback')
        await self.cancel_motion_callback(new='on')
        await self.listen_motion_off(await self.app.off_duration())

    async def callback_light_off(self, entity=None, attribute=None, old=None, new=None, kwargs=None):
        """Called when the light turns off
        """
        self.log('Light off callback')
        await self.cancel_motion_callback(new='off')
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

    async def cancel_motion_callback(self, new: str):
        callbacks = await self.get_sensor_callbacks()
        # self.log(f'Found {len(callbacks)}')
        for handle, info in callbacks.items():
            entity = info["entity"]
            new_match = re.match('new=(?P<new>.*?)\s', info['kwargs'])
            # self.log(f'{handle}: {info["entity"]}: {info["kwargs"]}')
            if new_match is not None and new_match.group("new") == new:
                await self.cancel_listen_state(handle)
                self.log(f'cancelled: {await self.friendly_name(entity)}: {new}')
