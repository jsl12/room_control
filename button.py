import asyncio
import json

from appdaemon.plugins.mqtt.mqttapi import Mqtt
from room_control import RoomController


class ButtonController(Mqtt):
    def initialize(self):
        task = self.get_app(self.args['app'])
        self.app: RoomController = asyncio.get_event_loop().run_until_complete(task)
        self.setup_buttons(self.args['button'])
        # self.log(f'Done')

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
        topic = data['topic']
        self.log(f'Button event for: {topic}')
        try:
            payload = json.loads(data['payload'])
            action = payload['action']
            button = kwargs['button']
        except json.JSONDecodeError:
            self.log(f'Error decoding JSON from {data["payload"]}', level='ERROR')
        except KeyError as e:
            return
        else:
            self.log(f'{button}: {action}')
            await self.handle_action(action)

    async def handle_action(self, action: str):
        if action == '':
            return
        elif action == 'single':
            cause = 'button single click'
            state = await self.get_state(entity_id=self.args['ref_entity'])
            if state == 'on':
                self.app.deactivate(cause=cause)
            else:
                await self.app.activate(cause=cause)
        else:
            pass