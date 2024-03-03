from appdaemon.adapi import ADAPI
from rich.console import Console
from rich.logging import RichHandler

console = Console(width=150)

handler = RichHandler(
    console=console,
    markup=True,
    show_path=False,
    log_time_format='%Y-%m-%d %I:%M:%S %p',
)


def setup_logging(self: ADAPI):
    if not any(isinstance(h, RichHandler) for h in self.logger.handlers):
        self.logger.propagate = False
        self.logger.addHandler(handler)
        self.log(f'Added rich handler for [bold green]{self.logger.name}[/]')
        self.log(f'Formatter [bold green]{self.logger.handlers[0].formatter}[/]')
