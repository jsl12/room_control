import logging
import re

from appdaemon.adapi import ADAPI
from appdaemon.logging import AppNameFormatter
from rich.console import Console
from rich.highlighter import RegexHighlighter
from rich.logging import RichHandler
from rich.theme import Theme


class RCHighlighter(RegexHighlighter):
    highlights = [
        r'(?P<light>(light|switch)\.\w+)',
        r'(?P<time>\d+:\d+:\d+)',
        r'(?P<z2m>zigbee2mqtt/)',
        r'(?P<sensor>binary_sensor\.\w+)',
        # r"'state': '(?P<on>on)|(?P<off>off)'"
        r'(?P<true>True)|(?P<false>False)',
    ]


console = Console(
    width=100,
    theme=Theme(
        {
            'log.time': 'none',
            'logging.level.info': 'none',
            'room': 'italic bright_cyan',
            'component': 'dark_violet',
            'friendly_name': 'yellow',
            'light': 'light_slate_blue',
            'sensor': 'green',
            'time': 'yellow',
            'z2m': 'bright_black',
            'topic': 'chartreuse2',
            'true': 'green',
            'false': 'red',
        }
    ),
    log_time_format='%Y-%m-%d %I:%M:%S %p',
    highlighter=RCHighlighter(),
)


class UnMarkupFormatter(AppNameFormatter):
    md_regex = re.compile(r'(?P<open>\[.*?\])(?P<text>.*?)(?P<close>\[\/\])')

    def format(self, record: logging.LogRecord):
        result = super().format(record)
        return self.md_regex.sub(r'\g<text>', result)


class RoomControllerFormatter(logging.Formatter):
    def __init__(self, room: str, component: str = None):
        self.log_fields = {'room': room}

        fmt = '[room]{room:>12}[/]'
        if component is not None:
            fmt += ' [component]{component:<9}[/]'
            self.log_fields['component'] = component
        fmt += ' {message}'

        datefmt = '%Y-%m-%d %I:%M:%S %p'
        style = '{'
        validate = True

        super().__init__(fmt, datefmt, style, validate)
        # console.print(f'Format: [bold yellow]{fmt}[/]')

    def format(self, record: logging.LogRecord):
        parts = record.name.split('.')
        record.room = parts[1]
        if len(parts) == 3:
            record.component = parts[2]

        return super().format(record)


def new_handler() -> RichHandler:
    return RichHandler(
        console=console,
        # highlighter=NullHighlighter(),
        highlighter=RCHighlighter(),
        markup=True,
        show_path=False,
        omit_repeated_times=False,
        log_time_format='%Y-%m-%d %I:%M:%S %p',
    )


def setup_handler(**kwargs) -> RichHandler:
    handler = new_handler()
    handler.setFormatter(RoomControllerFormatter(**kwargs))
    return handler


def setup_component_logging(self):
    typ = type(self).__name__
    logger = logging.getLogger(f'room_control.{self.args["app"]}')
    self.logger = logger.getChild(typ)
    if len(self.logger.handlers) == 0:
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(setup_handler(room=self.args['app'], component=typ))
        self.logger.propagate = False

