import json
from copy import deepcopy
from datetime import timedelta, time
from typing import List

import astral
from appdaemon.plugins.mqtt.mqttapi import Mqtt


class RoomController(Mqtt):
    def initialize(self):
        self.set_namespace('mqtt')

        self.app_entities = self.gather_app_entities()
        for entity in self.app_entities:
            topic = f'zigbee2mqtt/{entity}'
            self.mqtt_subscribe(topic)
            self.log(f'MQTT entity topic: {topic}')

        self.refresh_state_times()

        self.setup_motion(self.args['sensor'])

        if (button := self.args.get('button')):
            if not isinstance(button, list):
                button = [button]
            for button in button:
                self.setup_button(button)

    def setup_motion(self, name: str):
        def handle_motion(event_name, data, kwargs):
            sensor = kwargs['sensor']
            payload = json.loads(data['payload'])
            motion = payload['occupancy']
            self.log(f'motion: {sensor}: {motion}')
            # self.log(data['topic'])

        topic = f'zigbee2mqtt/{name}'
        self.mqtt_subscribe(topic)
        self.listen_event(handle_motion, "MQTT_MESSAGE", topic=topic, sensor=name)
        self.log(f'Subscribed to MQTT topic: {topic}')

    def setup_button(self, name: str):
        def handle_button(event_name, data, kwargs):
            button = kwargs['button']
            action = data['payload']

            func_name = f'handle_button_{action}'
            if (handler := getattr(self, func_name, None)) is not None:
                handler(button)
                self.log(f"button: {button}: {action}")
            else:
                self.log(f'Unhandled button action: {button}, {action}')

        topic = f'zigbee2mqtt/{name}/action'
        self.mqtt_subscribe(topic)
        self.listen_event(handle_button, "MQTT_MESSAGE", topic=topic, button=name)
        self.log(f'Subscribed to MQTT topic: {topic}')
    
    def handle_button_single(self, button: str):
        states = {entity: self.get_state(entity) for entity in self.app_entities}
        self.log(states)

        if self.any_on:
            self.deactivate()
        else:
            self.activate()
    
    def handle_button_double(self, button: str):
        return

    def handle_button_hold(self, button: str):
        return

    def handle_button_release(self, button: str):
        return
    
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

    def current_state(self, time: time = None):
        if self.sleep_bool:
            if (state := self.args.get('sleep_state')):
                return state
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
        
    @property
    def sleep_bool(self) -> bool:
        if (sleep_var := self.args.get('sleep')):
            return self.get_state(sleep_var) == 'on'
        else:
            return False

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

    def activate(self, *args, **kwargs):
        self.log('Activating')
        scene = self.current_scene()

        # if isinstance(scene, str):
        #     self.turn_on(scene)
        #     self.log(f'Turned on scene: {scene}')

        # elif isinstance(scene, dict):
        #     # makes setting the state to 'on' optional in the yaml definition
        #     for entity, settings in scene.items():
        #         if 'state' not in settings:
        #             scene[entity]['state'] = 'on'

        #     self.call_service('scene/apply', entities=scene, transition=0)
        #     self.log(f'Applied scene: {scene}')

        # elif scene is None:
        #     self.log(f'No scene, ignoring...')
        #     # Need to act as if the light had just turned off to reset the motion (and maybe other things?)
        #     self.callback_light_off()
        # else:
        #     self.log(f'ERROR: unknown scene: {scene}')

    def activate_all_off(self, *args, **kwargs):
        if self.all_off:
            self.activate()
        else:
            self.log(f'Skipped activating - everything is not off')

    def activate_any_on(self, *args, **kwargs):
        if self.any_on:
            self.activate()
        else:
            self.log(f'Skipped activating - everything is off')
    
    def deactivate(self, *args, **kwargs):
        self.log('Deactivating')
        # for entity in self.app_entities:
        #     self.turn_off(entity)
        #     self.log(f'Turned off {entity}')

    def callback_light_on(self, entity=None, attribute=None, old=None, new=None, kwargs=None):
        """Called when the light turns on
        """
        self.log('Light on callback')
        self.cancel_motion_callback(new='on')
        self.listen_motion_off(self.off_duration)

    def callback_light_off(self, entity=None, attribute=None, old=None, new=None, kwargs=None):
        """Called when the light turns off
        """
        self.log('Light off callback')
        self.cancel_motion_callback(new='off')
        self.listen_motion_on()
    
    def listen_motion_on(self):
        """Sets up the motion on callback to activate the room
        """
        self.log(f'Waiting for motion on {self.friendly_name(self.sensor)} to turn on {self.friendly_name(self.entity)}')
        self.motion_on_handle = self.listen_state(
            callback=self.activate,
            entity_id=self.sensor,
            new='on',
            oneshot=True
        )

    def listen_motion_off(self, duration: timedelta):
        """Sets up the motion off callback to deactivate the room
        """
        self.log(f'Waiting for motion to stop on {self.friendly_name(self.sensor)} for {duration} to turn off {self.friendly_name(self.entity)}')
        self.motion_off_handle = self.listen_state(
            callback=self.deactivate,
            entity_id=self.sensor,
            new='off',
            duration=duration.total_seconds(),
            oneshot=True
        )