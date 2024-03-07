import logging

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


handler = RichHandler(
    console=console,
    highlighter=NullHighlighter(),
    markup=True,
    show_path=False,
    omit_repeated_times=False,
    log_time_format='%Y-%m-%d %I:%M:%S %p',
)


handler.setFormatter(AppNameFormatter(fmt='[appname]{appname}[/] {message}', style='{'))


def init_logging(self: ADAPI, level):
    if not any(isinstance(h, RichHandler) for h in self.logger.handlers):
        self.logger.propagate = False
        self.logger.setLevel(level)
        self.logger.addHandler(handler)
        self.log(f'Added rich handler for [bold green]{self.logger.name}[/]')
        # self.log(f'Formatter for RichHandler: {handler.formatter}')


def deinit_logging(self: ADAPI):
    self.logger.setLevel(logging.NOTSET)
    self.logger.propagate = True
    for h in self.logger.handlers:
        if isinstance(h, RichHandler):
            self.logger.removeHandler(h)
            self.log('Removed RichHandler')
