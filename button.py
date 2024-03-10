import json
from dataclasses import dataclass

from appdaemon.plugins.mqtt.mqttapi import Mqtt
from console import setup_component_logging

from room_control import RoomController


@dataclass(init=False)
class Button(Mqtt):
    button: str
    rich: bool = False

    async def initialize(self):
        setup_component_logging(self)
        self.app: RoomController = await self.get_app(self.args['app'])
        self.log(f'Connected to AD app [room]{self.app.name}[/]')

        self.button = self.args['button']
        self.setup_buttons(self.button)

    def setup_buttons(self, buttons):
        if isinstance(buttons, list):
            for button in buttons:
                self.setup_button(button)
        else:
            self.setup_button(buttons)

    def setup_button(self, name: str):
        topic = f'zigbee2mqtt/{name}'
        # self.mqtt_subscribe(topic, namespace='mqtt')
        self.listen_event(self.handle_button, 'MQTT_MESSAGE', topic=topic, namespace='mqtt', button=name)
        self.log(f'MQTT topic [blue]{topic}[/] controls app [green]{self.app.name}[/]')

    def handle_button(self, event_name, data, kwargs):
        try:
            payload = json.loads(data['payload'])
            action = payload['action']
        except json.JSONDecodeError:
            self.log(f'Error decoding JSON from {data["payload"]}', level='ERROR')
        except KeyError:
            return
        else:
            if action != '':
                self.handle_action(action)

    def handle_action(self, action: str):
        if isinstance(action, str):
            action_str = f' [yellow]{action.upper()}[/] '

        if action == 'single':
            self.log(action_str.center(80, '='))
            state = self.get_state(self.args['ref_entity'])
            kwargs = {'kwargs': {'cause': f'button single click: toggle while {state}'}}
            if state == 'on':
                self.app.deactivate(**kwargs)
            else:
                self.app.activate(**kwargs)
        else:
            pass
