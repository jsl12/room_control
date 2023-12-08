import asyncio
from copy import deepcopy
from datetime import datetime, time, timedelta
from typing import Dict, List

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
        # self.log(f'entities: {self.app_entities}')
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
            t: time = state['time']
            try:
                await self.run_at(callback=self.activate_any_on, start=t.strftime('%H:%M:%S'), cause='scheduled transition')
            except ValueError:
                # happens when the callback time is in the past
                pass
            except Exception as e:
                self.log(f'Failed with {type(e)}: {e}')
            else:
                self.log(f'Scheduled transition at: {t.strftime("%I:%M:%S %p")}')

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
        # states = sorted(states, key=lambda s: s['time'], reverse=True)
        return states

    async def current_state(self, time: time = None):
        if (await self.sleep_bool()):
            self.log(f'sleep: active')
            if (state := self.args.get('sleep_state')):
                return state
            else:
                return {}
        else:
            # now: datetime = await self.get_now()
            # self.log(f'Getting state for datetime: {now.strftime("%I:%M:%S %p")}')
            time = time or (await self.get_now()).time()
            for state in self.states:
                if state['time'] <= time:
                    res = state
            else:
                self.log(f'Defaulting to first state')
                res = self.states[0]
            
            self.log(f'Selected state from {res["time"].strftime("%I:%M:%S %p")}')
            return res

    async def current_scene(self, time: time = None):
        if (state := (await self.current_state(time=time))) is not None:
            return state['scene']

    async def app_entity_states(self) -> Dict[str, str]:
        states = {
            entity: (await self.get_state(entity))
            for entity in self.app_entities
        }
        return states

    async def all_off(self) -> bool:
        """"All off" is the logic opposite of "any on"

        Returns:
            bool: Whether all the lights associated with the app are off
        """
        states = await self.app_entity_states()
        return all(state != 'on' for entity, state in states.items())

    async def any_on(self) -> bool:
        """"Any on" is the logic opposite of "all off"

        Returns:
            bool: Whether any of the lights associated with the app are on
        """
        states = await self.app_entity_states()
        return any(state == 'on' for entity, state in states.items())

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

    @utils.sync_wrapper
    async def activate(self, entity = None, attribute = None, old = None, new = None, kwargs = None):
        cause = kwargs.get('cause', 'unknown')
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

    @utils.sync_wrapper
    async def activate_all_off(self, *args, **kwargs):
        """Activate if all of the entities are off. Args and kwargs are passed directly to self.activate()
        """
        if (await self.all_off()):
            self.activate(*args, **kwargs)
        else:
            self.log(f'Skipped activating - everything is not off')

    @utils.sync_wrapper
    async def activate_any_on(self, *args, **kwargs):
        """Activate if any of the entities are on. Args and kwargs are passed directly to self.activate()
        """
        if (await self.any_on()):
            self.activate(*args, **kwargs)
        else:
            self.log(f'Skipped activating - everything is off')

    def deactivate(self, entity = None, attribute = None, old = None, new = None, kwargs = None):
        cause = kwargs.get('cause', 'unknown')
        self.log(f'Deactivating: {cause}')
        for e in self.app_entities:
            self.turn_off(e)
            self.log(f'Turned off {e}')
