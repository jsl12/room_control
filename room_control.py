import datetime
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import yaml
from appdaemon.entity import Entity
from appdaemon.plugins.hass.hassapi import Hass
from appdaemon.plugins.mqtt.mqttapi import Mqtt
from astral import SunDirection
from console import setup_logging


def str_to_timedelta(input_str: str) -> datetime.timedelta:
    try:
        hours, minutes, seconds = map(int, input_str.split(':'))
        return datetime.timedelta(hours=hours, minutes=minutes, seconds=seconds)
    except Exception:
        return datetime.timedelta()


@dataclass
class RoomState:
    scene: Dict[str, Dict[str, str | int]]
    off_duration: datetime.timedelta = None
    time: datetime.time = None
    time_fmt: List[str] = field(default_factory=lambda: ['%H:%M:%S', '%I:%M:%S %p'], repr=False)
    elevation: int | float = None
    direction: SunDirection = None

    def __post_init__(self):
        if isinstance(self.time, str):
            for fmt in self.time_fmt:
                try:
                    self.time = datetime.datetime.strptime(self.time, fmt).time()
                except Exception:
                    continue
                else:
                    break

        if self.elevation is not None:
            assert self.direction is not None, 'Elevation setting requires a direction'
            if self.direction.lower() == 'setting':
                self.direction = SunDirection.SETTING
            elif self.direction.lower() == 'rising':
                self.direction = SunDirection.RISING
            else:
                raise ValueError(f'Invalid sun direction: {self.direction}')

            if isinstance(self.elevation, str):
                self.elevation = float(self.elevation)

        if isinstance(self.off_duration, str):
            self.off_duration = str_to_timedelta(self.off_duration)

    @classmethod
    def from_json(cls, json_input):
        return cls(**json_input)


@dataclass
class RoomConfig:
    states: List[RoomState]
    off_duration: datetime.timedelta = None

    def __post_init__(self):
        if isinstance(self.off_duration, str):
            self.off_duration = str_to_timedelta(self.off_duration)

    @classmethod
    def from_app_config(cls, app_cfg: Dict[str, Dict]):
        if 'off_duration' in app_cfg:
            kwargs = {'off_duration': app_cfg['off_duration']}
        else:
            kwargs = {}

        self = cls(states=[RoomState.from_json(s) for s in app_cfg['states']], **kwargs)

        return self

    @classmethod
    def from_yaml(cls, yaml_path: Path, app_name: str):
        with yaml_path.open('r') as f:
            cfg: Dict = yaml.load(f, Loader=yaml.SafeLoader)[app_name]
        return cls.from_app_config(cfg)

    def sort_states(self):
        """Should only be called after all the times have been resolved"""
        assert all(isinstance(state.time, datetime.time) for state in self.states), 'Times have not all been resolved yet'
        self.states = sorted(self.states, key=lambda s: s.time, reverse=True)

    def current_state(self, now: datetime.time) -> RoomState:
        # time_fmt = '%I:%M:%S %p'
        # print(now.strftime(time_fmt))

        self.sort_states()
        for state in self.states:
            if state.time <= now:
                return state
        else:
            # self.log(f'Defaulting to first state')
            return self.states[0]

    def current_scene(self, now: datetime.time) -> Dict:
        state = self.current_state(now)
        return state.scene

    def current_off_duration(self, now: datetime.time) -> datetime.timedelta:
        state = self.current_state(now)
        if state.off_duration is None:
            if self.off_duration is None:
                raise ValueError('Need an off duration')
            else:
                return self.off_duration
        else:
            return state.off_duration


class RoomController(Hass, Mqtt):
    """Class for linking an light with a motion sensor.

    - Separate the turning on and turning off functions.
    - Use the state change of the light to set up the event for changing to the other state
        - `handle_on`
        - `handle_off`
    - When the light comes on, check if it's attributes match what they should, given the time.
    """

    @property
    def states(self) -> List[RoomState]:
        return self._room_config.states

    @states.setter
    def states(self, new: List[RoomState]):
        assert all(isinstance(s, RoomState) for s in new), f'Invalid: {new}'
        self._room_config.states = new

    def initialize(self):
        if self.args.get('rich', False):
            setup_logging(self)

        self.app_entities = self.gather_app_entities()
        # self.log(f'entities: {self.app_entities}')
        self.refresh_state_times()
        self.run_daily(callback=self.refresh_state_times, start='00:00:00')

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

        entities = [e for e in generator()]
        return set(entities)

    def refresh_state_times(self, *args, **kwargs):
        """Resets the `self.states` attribute to a newly parsed version of the states.

        Parsed states have an absolute time for the current day.
        """
        # re-parse the state strings into times for the current day
        self._room_config = RoomConfig.from_app_config(self.args)
        self.log(f'{len(self._room_config.states)} states in the RoomConfig')

        for state in self._room_config.states:
            if state.time is None and state.elevation is not None:
                state.time = self.AD.sched.location.time_at_elevation(
                    elevation=state.elevation, direction=state.direction
                ).time()
            elif isinstance(state.time, str):
                state.time = self.parse_time(state.time)

            assert isinstance(state.time, datetime.time), f'Invalid time: {state.time}'

        for state in self.states:
            self.log(f'State: {state.time.strftime("%I:%M:%S %p")} {state.scene}')

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

    def current_state(self, now: datetime.time = None) -> RoomState:
        if self.sleep_bool():
            self.log('sleep: active')
            if state := self.args.get('sleep_state'):
                return RoomState.from_json(state)
            else:
                return RoomState(scene={})
        else:
            now = now or self.get_now().time()
            self.log(f'Getting state for {now}', level='DEBUG')

            state = self._room_config.current_state(now)
            self.log(f'Current state: {state}', level='DEBUG')

            return state

    def current_scene(self, now: datetime.time = None) -> Dict[str, Dict[str, str | int]]:
        state = self.current_state(now)
        # print(f'{type(state).__name__}')
        # assert isinstance(state, RoomState), f'Invalid state: {type(state).__name__}'
        assert type(state).__name__ == 'RoomState'  # needed for the reloading to work
        # self.log(f'Current scene: {state}')
        self.log('Current scene:')
        self.log(state)
        return state.scene

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
        scene = self.current_scene()

        if isinstance(scene, str):
            self.turn_on(scene)
            self.log(f'Turned on scene: {scene}')

        elif isinstance(scene, dict):
            # makes setting the state to 'on' optional in the yaml definition
            for entity, settings in scene.items():
                if 'state' not in settings:
                    scene[entity]['state'] = 'on'

            self.call_service('scene/apply', entities=scene, transition=0)
            self.log(f'Applied scene: {scene}')

        elif scene is None:
            self.log('No scene, ignoring...')
            # Need to act as if the light had just turned off to reset the motion (and maybe other things?)
            # self.callback_light_off()
        else:
            self.log(f'ERROR: unknown scene: {scene}')

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
