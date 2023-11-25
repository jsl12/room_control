import asyncio
from copy import deepcopy
from datetime import time, timedelta
from typing import List

import appdaemon.utils as utils
import astral
from appdaemon.entity import Entity
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

    async def initialize(self):
        self.app_entities = await self.gather_app_entities()
        self.log(f'entities: {self.app_entities}')
        await self.refresh_state_times()
        await self.run_daily(callback=self.refresh_state_times, start='00:00:00')

        # if (ha_button := self.args.get('ha_button')):
        #     self.log(f'Setting up input button: {self.friendly_name(ha_button)}')
        #     self.listen_state(callback=self.activate_any_on, entity_id=ha_button)

    async def gather_app_entities(self) -> List[str]:
        """Returns a list of all the entities involved in any of the states
        """
        async def async_generator():
            for settings in deepcopy(self.args['states']):
                if (scene := settings.get('scene')):
                    if isinstance(scene, str):
                        assert scene.startswith('scene.'), f"Scene definition must start with 'scene.' for app {self.name}"
                        entity: Entity = self.get_entity(scene)
                        entity_state = await entity.get_state('all')
                        attributes = entity_state['attributes']
                        for entity in attributes['entity_id']:
                            yield entity
                    else:
                        for key in scene.keys():
                            yield key
                else:
                    yield self.args['entity']

        entities = [e async for e in async_generator()]
        return set(entities)

    async def refresh_state_times(self, *args, **kwargs):
        """Resets the `self.states` attribute to a newly parsed version of the states.

        Parsed states have an absolute time for a certain day. 
        """
        # re-parse the state strings into times for the current day
        self.states = await self.parse_states()

        # schedule the transitions
        for state in self.states:
            dt = str(state['time'])[:8]
            self.log(f'Scheduling transition at: {dt}')
            try:
                await self.run_at(callback=self.activate_any_on, start=dt)
            except ValueError:
                # happens when the callback time is in the past
                pass
            except Exception as e:
                self.log(f'Failed with {type(e)}: {e}')

    async def parse_states(self):
        async def gen():
            for state in deepcopy(self.args['states']):
                if (time := state.get('time')):
                    state['time'] = await self.parse_time(time)

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

        states = [s async for s in gen()]
        states = sorted(states, key=lambda s: s['time'])
        return states

    async def current_state(self, time: time = None):
        if (await self.sleep_bool()):
            if (state := self.args.get('sleep_state')):
                return state
            else:
                return {}
        else:
            now = await self.get_now()
            self.log(f'Getting state for datetime: {now}')
            time = time or (await self.get_now()).time()
            for state in self.states[::-1]:
                if state['time'] <= time:
                    self.log(f'Selected state from {state["time"]}')
                    return state
            else:
                return self.states[-1]

    async def current_scene(self, time: time = None):
        if (state := (await self.current_state(time=time))) is not None:
            return state['scene']

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

    async def sleep_bool(self) -> bool:
        if (sleep_var := self.args.get('sleep')):
            return (await self.get_state(sleep_var)) == 'on'
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

    async def off_duration(self) -> timedelta:
        """Determines the time that the motion sensor has to be clear before deactivating

        Priority:
        - Value in scene definition
        - Default value
            - Normal - value in app definition
            - Sleep - 0

        """
        current_state = await self.current_state()
        duration_str = current_state.get(
            'off_duration',
            self.args.get('off_duration', '00:00:00')
        )

        try:
            hours, minutes, seconds = map(int, duration_str.split(':'))
            return timedelta(hours=hours, minutes=minutes, seconds=seconds)
        except Exception:
            return timedelta()

    async def activate(self, *args, cause: str = 'unknown', **kwargs):
        self.log(f'Activating: {cause}')
        scene = await self.current_scene()

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
            # self.callback_light_off()
        else:
            self.log(f'ERROR: unknown scene: {scene}')

    async def activate_all_off(self, *args, **kwargs):
        """Activate if all of the entities are off
        """
        if self.all_off:
            self.log(f'Activate all off kwargs: {kwargs}')
            await self.activate(*args, **kwargs)
        else:
            self.log(f'Skipped activating - everything is not off')

    async def activate_any_on(self, *args, **kwargs):
        """Activate if any of the entities are on
        """
        if self.any_on:
            await self.activate(*args, **kwargs)
        else:
            self.log(f'Skipped activating - everything is off')

    def deactivate(self, *args, cause: str = 'unknown', **kwargs):
        self.log(f'Deactivating: {cause}')
        for entity in self.app_entities:
            self.turn_off(entity)
            self.log(f'Turned off {entity}')

