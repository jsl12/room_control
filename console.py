import logging
import re

from appdaemon.adapi import ADAPI
from appdaemon.logging import AppNameFormatter
from rich.console import Console
from rich.highlighter import NullHighlighter
from rich.logging import RichHandler
from rich.theme import Theme

console = Console(
    width=150,
    theme=Theme({'appname': 'italic bright_cyan'}),
)


class UnMarkupFormatter(AppNameFormatter):
    md_regex = re.compile(r'(?P<open>\[.*?\])(?P<text>.*?)(?P<close>\[\/\])')

    def format(self, record: logging.LogRecord):
        result = super().format(record)
        return self.md_regex.sub(r'\g<text>', result)


def create_handler() -> RichHandler:
    handler = RichHandler(
        console=console,
        highlighter=NullHighlighter(),
        markup=True,
        show_path=False,
        omit_repeated_times=False,
        log_time_format='%Y-%m-%d %I:%M:%S %p',
    )
    handler.setFormatter(AppNameFormatter(fmt='[appname]{appname}[/] {message}', style='{'))
    return handler


def init_logging(self: ADAPI, level):
    for h in logging.getLogger('AppDaemon').handlers:
        og_formatter = h.formatter
        h.setFormatter(
            UnMarkupFormatter(fmt=og_formatter._fmt, datefmt=og_formatter.datefmt, style='{')
        )

    if not any(isinstance(h, RichHandler) for h in self.logger.handlers):
        self.logger.propagate = False
        self.logger.setLevel(level)
        self.logger.addHandler(create_handler())
        self.log(f'Added rich handler for [bold green]{self.logger.name}[/]')
        # self.log(f'Formatter for RichHandler: {handler.formatter}')


def deinit_logging(self: ADAPI):
    self.logger.setLevel(logging.NOTSET)
    self.logger.propagate = True
    for h in self.logger.handlers:
        if isinstance(h, RichHandler):
            self.logger.removeHandler(h)
            self.log('Removed RichHandler')
