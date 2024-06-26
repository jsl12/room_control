import re
from datetime import timedelta
from typing import Literal, Optional

from appdaemon.entity import Entity
from appdaemon.plugins.hass.hassapi import Hass
from console import setup_component_logging
from pydantic import BaseModel, TypeAdapter

from room_control import RoomController


class CallbackEntry(BaseModel):
    entity: str
    event: Optional[str] = None
    type: Literal['state', 'event']
    kwargs: str
    function: str
    name: str
    pin_app: bool
    pin_thread: int


Callbacks = dict[str, dict[str, CallbackEntry]]


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
        setup_component_logging(self)
        self.app: RoomController = self.get_app(self.args['app'])
        self.log(f'Connected to AD app [room]{self.app.name}[/]', level='DEBUG')

        assert self.entity_exists(self.args['sensor'])
        assert self.entity_exists(self.args['ref_entity'])

        base_kwargs = dict(
            entity_id=self.ref_entity.entity_id,
            immediate=True,  # avoids needing to sync the state
        )

        if self.sensor_state != self.ref_entity_state:
            self.log(
                f'Sensor is {self.sensor_state} ' f'and light is {self.ref_entity_state}',
                level='WARNING',
            )
            if self.sensor_state:
                self.app.activate(kwargs={'cause': f'Syncing state with {self.sensor.entity_id}'})

        # don't need to await these because they'll already get turned into a task by the utils.sync_wrapper decorator
        self.listen_state(
            **base_kwargs,
            attribute='brightness',
            callback=self.callback_light_on,
        )
        self.listen_state(**base_kwargs, new='off', callback=self.callback_light_off)

        if callbacks := self.callbacks():
            for handle, entry in callbacks.items():
                self.log(f'Handle [yellow]{handle[:4]}[/]: {entry.function}')

    def callbacks(self):
        data = TypeAdapter(Callbacks).validate_python(self.get_callback_entries())
        name: str = self.name
        try:
            return data[name]
        except KeyError:
            return []

    def listen_motion_on(self):
        """Sets up the motion on callback to activate the room"""
        self.cancel_motion_callback()
        self.listen_state(
            callback=self.app.activate_all_off,
            entity_id=self.sensor.entity_id,
            new='on',
            oneshot=True,
            cause='motion on',
        )
        self.log(f'Waiting for motion on [friendly_name]{self.sensor.friendly_name}[/]')
        if self.sensor_state:
            self.log(
                f'[friendly_name]{self.sensor.friendly_name}[/] is already on', level='WARNING'
            )

    def listen_motion_off(self, duration: timedelta):
        """Sets up the motion off callback to deactivate the room"""
        self.cancel_motion_callback()
        self.listen_state(
            callback=self.app.deactivate,
            entity_id=self.sensor.entity_id,
            new='off',
            duration=duration.total_seconds(),
            oneshot=True,
            cause='motion off',
        )
        self.log(
            f'Waiting for [friendly_name]{self.sensor.friendly_name}[/] to be clear for {duration}'
        )

        if not self.sensor_state:
            self.log(
                f'[friendly_name]{self.sensor.friendly_name}[/] is currently off', level='WARNING'
            )

    def callback_light_on(self, entity=None, attribute=None, old=None, new=None, kwargs=None):
        """Called when the light turns on"""
        if new is not None:
            self.log(f'Detected {entity} turning on', level='DEBUG')
            duration = self.app.off_duration()
            self.listen_motion_off(duration)

    def callback_light_off(self, entity=None, attribute=None, old=None, new=None, kwargs=None):
        """Called when the light turns off"""
        self.log(f'Detected {entity} turning off', level='DEBUG')
        self.listen_motion_on()

    def get_app_callbacks(self, name: str = None):
        """Gets all the callbacks associated with the app"""
        name = name or self.name
        callbacks = {
            handle: info
            for app_name, callbacks in self.get_callback_entries().items()
            for handle, info in callbacks.items()
            if app_name == name
        }
        return callbacks

    def get_sensor_callbacks(self):
        return {
            handle: info
            for handle, info in self.get_app_callbacks().items()
            if info['entity'] == self.sensor.entity_id
        }

    def cancel_motion_callback(self):
        callbacks = self.get_sensor_callbacks()
        # self.log(f'Found {len(callbacks)} callbacks for {self.sensor.entity_id}')
        for handle, info in callbacks.items():
            entity = info['entity']
            kwargs = info['kwargs']
            if (m := re.match('new=(?P<new>.*?)\s', kwargs)) is not None:
                new = m.group('new')
                self.cancel_listen_state(handle)
                self.log(f'cancelled callback for sensor {entity} turning {new}', level='DEBUG')
