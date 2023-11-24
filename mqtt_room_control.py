import json
from appdaemon.plugins.mqtt.mqttapi import Mqtt


class RoomController(Mqtt):
    def initialize(self):
        self.set_namespace('mqtt')

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
            self.log(data['topic'])

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
        return
    
    def handle_button_double(self, button: str):
        return

    def handle_button_hold(self, button: str):
        return

    def handle_button_release(self, button: str):
        return
    
