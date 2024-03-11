import datetime
import logging
from copy import deepcopy
from typing import Dict, List

from appdaemon.entity import Entity
from appdaemon.plugins.hass.hassapi import Hass
from appdaemon.plugins.mqtt.mqttapi import Mqtt
from console import console, setup_handler
from model import ControllerStateConfig, RoomControllerConfig

logger = logging.getLogger(__name__)


class RoomController(Hass, Mqtt):
    """Class for linking room's lights with a motion sensor.

    - Separate the turning on and turning off functions.
    - Use the state change of the light to set up the event for changing to the other state
        - `handle_on`
        - `handle_off`
    - When the light comes on, check if it's attributes match what they should, given the time.
    """

    @property
    def states(self) -> List[ControllerStateConfig]:
        return self._room_config.states

    @states.setter
    def states(self, new: List[ControllerStateConfig]):
        assert all(isinstance(s, ControllerStateConfig) for s in new), f'Invalid: {new}'
        self._room_config.states = new

    def initialize(self):
        self.logger = logger.getChild(self.name)
        if not self.logger.hasHandlers():
            self.logger.setLevel(self.args.get('rich', logging.INFO))
            self.logger.addHandler(setup_handler(room=self.name))
            # console.log(f'[yellow]Added RichHandler to {self.logger.name}[/]')

        self.app_entities = self.gather_app_entities()
        # self.log(f'entities: {self.app_entities}')
        self.refresh_state_times()
        self.run_daily(callback=self.refresh_state_times, start='00:00:00')
        self.log(f'Initialized [bold green]{type(self).__name__}[/]')

    def terminate(self):
        self.log('[bold red]Terminating[/]', level='DEBUG')

    def gather_app_entities(self) -> List[str]:
        """Returns a list of all the entities involved in any of the states"""

        def generator():
            for settings in deepcopy(self.args['states']):
                if scene := settings.get('scene'):
                    if isinstance(scene, str):
                        assert scene.startswith(
                            'scene.'
                        ), f"Scene definition must start with 'scene.' for app {self.name}"
                        entity: Entity = self.get_entity(scene)
                        entity_state = entity.get_state('all')
                        attributes = entity_state['attributes']
                        for entity in attributes['entity_id']:
                            yield entity
                    else:
                        for key in scene.keys():
                            yield key
                else:
                    yield self.args['entity']

        return set(list(generator()))

    def refresh_state_times(self, *args, **kwargs):
        """Resets the `self.states` attribute to a newly parsed version of the states.

        Parsed states have an absolute time for the current day.
        """
        # re-parse the state strings into times for the current day
        self._room_config = RoomControllerConfig(**self.args)
        self.log(f'{len(self._room_config.states)} states in the app configuration', level='DEBUG')

        for state in self._room_config.states:
            if state.time is None and state.elevation is not None:
                state.time = self.AD.sched.location.time_at_elevation(
                    elevation=state.elevation, direction=state.direction
                ).time()
            elif isinstance(state.time, str):
                state.time = self.parse_time(state.time)

            assert isinstance(state.time, datetime.time), f'Invalid time: {state.time}'

        if self.logger.isEnabledFor(logging.DEBUG):
            # table = self._room_config.rich_table(self.name)
            console.print(self._room_config)

        self.states = sorted(self.states, key=lambda s: s.time, reverse=True)

        # schedule the transitions
        for state in self.states[::-1]:
            # t: datetime.time = state['time']
            t: datetime.time = state.time
            try:
                self.run_at(callback=self.activate_any_on, start=t.strftime('%H:%M:%S'), cause='scheduled transition')
            except ValueError:
                # happens when the callback time is in the past
                pass
            except Exception as e:
                self.log(f'Failed with {type(e)}: {e}')

    def current_state(self, now: datetime.time = None) -> ControllerStateConfig:
        if self.sleep_bool():
            self.log('sleep: active')
            if state := self.args.get('sleep_state'):
                return ControllerStateConfig(**state)
            else:
                return ControllerStateConfig(scene={})
        else:
            now = now or self.get_now().time().replace(microsecond=0)
            self.log(f'Getting state for {now.strftime("%I:%M:%S %p")}', level='DEBUG')

            state = self._room_config.current_state(now)
            self.log(f'Current state: {state.time}', level='DEBUG')
            return state

    def app_entity_states(self) -> Dict[str, str]:
        states = {entity: self.get_state(entity) for entity in self.app_entities}
        return states

    def all_off(self) -> bool:
        """ "All off" is the logic opposite of "any on"

        Returns:
            bool: Whether all the lights associated with the app are off
        """
        states = self.app_entity_states()
        return all(state != 'on' for entity, state in states.items())

    def any_on(self) -> bool:
        """ "Any on" is the logic opposite of "all off"

        Returns:
            bool: Whether any of the lights associated with the app are on
        """
        states = self.app_entity_states()
        return any(state == 'on' for entity, state in states.items())

    def sleep_bool(self) -> bool:
        if sleep_var := self.args.get('sleep'):
            return self.get_state(sleep_var) == 'on'
        else:
            return False

    # @sleep_bool.setter
    # def sleep_bool(self, val) -> bool:
    #     if (sleep_var := self.args.get('sleep')):
    #         if isinstance(val, str):
    #             self.set_state(sleep_var, state=val)
    #         elif isinstance(val, bool):
    #             self.set_state(sleep_var, state='on' if val else 'off')
    #     else:
    #         raise ValueError('Sleep variable is undefined')

    def off_duration(self, now: datetime.time = None) -> datetime.timedelta:
        """Determines the time that the motion sensor has to be clear before deactivating

        Priority:
        - Value in scene definition
        - Default value
            - Normal - value in app definition
            - Sleep - 0

        """
        sleep_mode_active = self.sleep_bool()
        if sleep_mode_active:
            self.log(f'Sleeping mode active: {sleep_mode_active}')
            return datetime.timedelta()
        else:
            now = now or self.get_now().time()
            return self._room_config.current_off_duration(now)

    def activate(self, entity=None, attribute=None, old=None, new=None, kwargs=None):
        if kwargs is not None:
            cause = kwargs.get('cause', 'unknown')
        else:
            cause = 'unknown'

        self.log(f'Activating: {cause}')
        scene_kwargs = self.current_state().to_apply_kwargs(transition=0)

        if isinstance(scene_kwargs, str):
            self.turn_on(scene_kwargs)
            self.log(f'Turned on scene: {scene_kwargs}')

        elif isinstance(scene_kwargs, dict):
            self.call_service('scene/apply', **scene_kwargs)
            if self.logger.isEnabledFor(logging.INFO):
                self.log('Applied scene:')
                console.print(scene_kwargs['entities'])

        elif scene_kwargs is None:
            self.log('No scene, ignoring...')
            # Need to act as if the light had just turned off to reset the motion (and maybe other things?)
            # self.callback_light_off()
        else:
            self.log(f'ERROR: unknown scene: {scene_kwargs}')

    def activate_all_off(self, *args, **kwargs):
        """Activate if all of the entities are off. Args and kwargs are passed directly to self.activate()"""
        if self.all_off():
            self.activate(*args, **kwargs)
        else:
            self.log('Skipped activating - everything is not off')

    def activate_any_on(self, *args, **kwargs):
        """Activate if any of the entities are on. Args and kwargs are passed directly to self.activate()"""
        if self.any_on():
            self.activate(*args, **kwargs)
        else:
            self.log('Skipped activating - everything is off')

    def toggle_activate(self, *args, **kwargs):
        if self.any_on():
            self.deactivate(*args, **kwargs)
        else:
            self.activate(*args, **kwargs)

    def deactivate(self, entity=None, attribute=None, old=None, new=None, kwargs=None):
        cause = kwargs.get('cause', 'unknown')
        self.log(f'Deactivating: {cause}')
        for e in self.app_entities:
            self.turn_off(e)
            self.log(f'Turned off {e}')
