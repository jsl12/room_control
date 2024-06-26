import json
from dataclasses import dataclass
from typing import List

from appdaemon.plugins.mqtt.mqttapi import Mqtt
from console import setup_component_logging
from model import ButtonConfig

from room_control import RoomController


@dataclass(init=False)
class Button(Mqtt):
    button: str | List[str]
    rich: bool = False
    config: ButtonConfig

    async def initialize(self):
        self.config = ButtonConfig(**self.args)
        setup_component_logging(self)
        self.app: RoomController = await self.get_app(self.args['app'])
        self.log(f'Connected to AD app [room]{self.app.name}[/]', level='DEBUG')

        self.button = self.config.button
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
        self.log(f'MQTT topic [topic]{topic}[/] controls app [room]{self.app.name}[/]')

    def handle_button(self, event_name, data, kwargs):
        try:
            payload = json.loads(data['payload'])
            action = payload['action']
        except json.JSONDecodeError:
            self.log(f'Error decoding JSON from {data["payload"]}', level='ERROR')
        except KeyError:
            return
        else:
            if isinstance(action, str) and action != '':
                self.log(f'Action: [yellow]{action}[/]')
                self.handle_action(action)

    def handle_action(self, action: str):
        if action == 'single':
            state = self.get_state(self.args['ref_entity'])
            kwargs = {'kwargs': {'cause': f'button single click: toggle while {state}'}}
            if state == 'on':
                self.app.deactivate(**kwargs)
            else:
                self.app.activate(**kwargs)
        else:
            pass
