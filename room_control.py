import json
from copy import deepcopy
from datetime import time, timedelta
from typing import List

import astral
from appdaemon.plugins.hass.hassapi import Hass
from appdaemon.plugins.mqtt.mqttapi import Mqtt


class RoomController(Hass, Mqtt):
    """Class for linking an light with a motion sensor.

    - Separate the turning on and turning off functions.
    - Use the state change of the light to set up the event for changing to the other state
        - `handle_on`
        - `handle_off`
    - When the light comes on, check if it's attributes match what they should, given the time.
    """

    def initialize(self):
        self.app_entities = self.gather_app_entities()
        
        self.refresh_state_times()
        self.run_daily(callback=self.refresh_state_times, start='00:00:00')

        # sets up motion callbacks
        # self.state_change_handle = self.listen_state(self.handle_state_change, self.entity)
        # self.sync_state()

        if (ha_button := self.args.get('ha_button')):
            self.log(f'Setting up input button: {self.friendly_name(ha_button)}')
            self.listen_state(callback=self.activate_any_on, entity_id=ha_button)
    
    @property
    def entity(self) -> str:
        return self.args['entity']

    @property
    def entity_state(self) -> bool:
        return self.get_state(self.entity) == 'on'

    @entity_state.setter
    def entity_state(self, new):
        if isinstance(new, str):
            if new == 'on':
                self.turn_on(self.entity)
            elif new == 'off':
                self.turn_on(self.entity)
            else:
                raise ValueError(f'Invalid value for entity state: {new}')
        elif isinstance(new, bool):
            if new:
                self.turn_on(self.entity)
                self.log(f'Turned on {self.friendly_name(self.entity)}')
            else:
                self.turn_off(self.entity)
                self.log(f'Turned off {self.friendly_name(self.entity)}')
        elif isinstance(new, dict):
            if any(isinstance(val, dict) for val in new.values()):
                # self.log(f'Setting scene with nested dict: {new}')
                for entity, state in new.items():
                    if state.pop('state', 'on') == 'on':
                        # self.log(f'Setting {entity} state with: {state}')
                        self.turn_on(entity_id=entity, **state)
                    else:
                        self.turn_off(entity)
            else:
                if new.pop('state', 'on') == 'on':
                    self.turn_on(self.entity, **new)
                else:
                    self.turn_off(self.entity)

        else:
            raise TypeError(f'Invalid type: {type(new)}: {new}')

    def parse_states(self):
        def gen():
            for state in deepcopy(self.args['states']):
                if (time := state.get('time')):
                    state['time'] = self.parse_time(time)

                elif isinstance((elevation := state.get('elevation')), (int, float)):
                    assert 'direction' in state, f'State needs a direction if it has an elevation'

                    if state['direction'] == 'rising':
                        dir = astral.SunDirection.RISING
                    elif state['direction'] == 'setting':
                        dir = astral.SunDirection.SETTING
                    else:
                        raise ValueError(f'Invalid sun direction: {state["direction"]}')

                    state['time'] = self.AD.sched.location.time_at_elevation(
                        elevation=elevation, direction=dir
                    ).time()

                else:
                    raise ValueError(f'Missing time')

                yield state

        states = sorted(gen(), key=lambda s: s['time'])
        return states

    def current_state(self, time: time = None):
        if self.sleep_bool:
            if (state := self.args.get('sleep_state')):
                return state
            else:
                return {}
        else:
            time = time or self.get_now().time()
            for state in self.states[::-1]:
                if state['time'] <= time:
                    return state
            else:
                return self.states[-1]

    def current_scene(self, time: time = None):
        if (state := self.current_state(time=time)) is not None:
            return state['scene']

    def gather_app_entities(self) -> List[str]:
        """Returns a list of all the entities involved in any of the states
        """
        def gen():
            for settings in deepcopy(self.args['states']):
                # dt = self.parse_time(settings.pop('time'))
                if (scene := settings.get('scene')):
                    if isinstance(scene, str):
                        yield from self.get_entity(scene).get_state('all')['attributes']['entity_id']
                    else:
                        yield from scene.keys()
                else:
                    yield self.args['entity']

        return list(set(gen()))

    @property
    def all_off(self) -> bool:
        """"All off" is the logic opposite of "any on"

        Returns:
            bool: Whether all the lights associated with the app are off
        """
        return all(self.get_state(entity) != 'on' for entity in self.app_entities)

    @property
    def any_on(self) -> bool:
        """"Any on" is the logic opposite of "all off"

        Returns:
            bool: Whether any of the lights associated with the app are on
        """
        return any(self.get_state(entity) == 'on' for entity in self.app_entities)

    @property
    def delay(self) -> timedelta:
        try:
            hours, minutes, seconds = map(int, self.args['delay'].split(':'))
            return timedelta(hours=hours, minutes=minutes, seconds=seconds)
        except Exception:
            return timedelta()

    @property
    def sleep_bool(self) -> bool:
        if (sleep_var := self.args.get('sleep')):
            return self.get_state(sleep_var) == 'on'
        else:
            # self.log('WARNING')
            return False

    @sleep_bool.setter
    def sleep_bool(self, val) -> bool:
        if (sleep_var := self.args.get('sleep')):
            if isinstance(val, str):
                self.set_state(sleep_var, state=val)
            elif isinstance(val, bool):
                self.set_state(sleep_var, state='on' if val else 'off')
        else:
            raise ValueError('Sleep variable is undefined')

    def activate(self, *args, cause: str = 'unknown', **kwargs):
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
            self.log(f'No scene, ignoring...')
            # Need to act as if the light had just turned off to reset the motion (and maybe other things?)
            self.callback_light_off()
        else:
            self.log(f'ERROR: unknown scene: {scene}')

    def activate_all_off(self, *args, **kwargs):
        """Activate if all of the entities are off
        """
        if self.all_off:
            self.activate(*args, **kwargs)
        else:
            self.log(f'Skipped activating - everything is not off')

    def activate_any_on(self, *args, **kwargs):
        """Activate if any of the entities are on
        """
        if self.any_on:
            self.activate(*args, **kwargs)
        else:
            self.log(f'Skipped activating - everything is off')

    def deactivate(self, *args, cause: str = 'unknown', **kwargs):
        self.log(f'Deactivating: {cause}')
        for entity in self.app_entities:
            self.turn_off(entity)
            self.log(f'Turned off {entity}')

    def refresh_state_times(self, *args, **kwargs):
        """Resets the `self.states` attribute to a newly parsed version of the states.

        Parsed states have an absolute time for a certain day. 
        """
        # re-parse the state strings into times for the current day
        self.states = self.parse_states()

        # schedule the transitions
        for state in self.states:
            dt = str(state['time'])[:8]
            self.log(f'Scheduling transition at: {dt}')
            try:
                self.run_at(callback=self.activate_any_on, start=dt)
            except ValueError:
                # happens when the callback time is in the past
                pass
            except Exception as e:
                self.log(f'Failed with {type(e)}: {e}')
