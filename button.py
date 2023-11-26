import asyncio
import json

from appdaemon.plugins.mqtt.mqttapi import Mqtt
from room_control import RoomController


class Button(Mqtt):
    async def initialize(self):
        self.app: RoomController = await self.get_app(self.args['app'])
        self.setup_buttons(self.args['button'])

    def setup_buttons(self, buttons):
        if isinstance(buttons, list):
            for button in buttons: 
                self.setup_button(button)
        else:
            self.setup_button(buttons)

    def setup_button(self, name: str):
        topic = f'zigbee2mqtt/{name}'
        self.mqtt_subscribe(topic, namespace='mqtt')
        self.listen_event(self.handle_button, "MQTT_MESSAGE", topic=topic, namespace='mqtt', button=name)
        self.log(f'"{topic}" controls app {self.app.name}')

    async def handle_button(self, event_name, data, kwargs):
        try:
            payload = json.loads(data['payload'])
            action = payload['action']
        except json.JSONDecodeError:
            self.log(f'Error decoding JSON from {data["payload"]}', level='ERROR')
        except KeyError as e:
            return
        else:
            if action != '':
                await self.handle_action(action)

    async def handle_action(self, action: str):
        if action == 'single':
            self.log(f' {action.upper()} '.center(50, '='))
            await self.app.toggle(kwargs={'cause': 'button single click'})
        else:
            pass