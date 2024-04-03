from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Dict, List, Optional, Self

import yaml
from astral import SunDirection
from pydantic import BaseModel, BeforeValidator, Field, root_validator
from pydantic_core import PydanticCustomError
from rich.console import Console, ConsoleOptions, RenderResult
from rich.table import Column, Table


def str_to_timedelta(input_str: str) -> timedelta:
    try:
        hours, minutes, seconds = map(int, input_str.split(':'))
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)
    except Exception:
        return timedelta()


def str_to_direction(input_str: str) -> SunDirection:
    try:
        return getattr(SunDirection, input_str.upper())
    except AttributeError:
        raise PydanticCustomError(
            'invalid_dir', 'Invalid sun direction: {dir}', dict(dir=input_str)
        )


OffDuration = Annotated[timedelta, BeforeValidator(str_to_timedelta)]


class State(BaseModel):
    state: bool = True
    brightness: Optional[int] = Field(default=None, ge=1, le=255)
    color_temp: Optional[int] = Field(default=None, ge=200, le=650)
    rgb_color: Optional[list[int]] = Field(default=None, min_length=3, max_length=3)


class ApplyKwargs(BaseModel):
    """Arguments to call with the 'scene/apply' service"""

    entities: Dict[str, State]
    transition: Optional[int] = None


class ControllerStateConfig(BaseModel):
    time: Optional[str | datetime] = None
    elevation: Optional[float] = None
    direction: Optional[Annotated[SunDirection, BeforeValidator(str_to_direction)]] = None
    off_duration: Optional[OffDuration] = None
    scene: dict[str, State]

    @root_validator(pre=True)
    def check_args(cls, values):
        time, elevation = values.get('time'), values.get('elevation')
        if time is not None and elevation is not None:
            raise PydanticCustomError('bad_time_spec', 'Only one of time or elevation can be set.')
        elif elevation is not None and 'direction' not in values:
            raise PydanticCustomError('no_sun_dir', 'Needs sun direction with elevation')
        return values

    def to_apply_kwargs(self, **kwargs):
        return ApplyKwargs(entities=self.scene, **kwargs).model_dump(exclude_none=True)


class RoomControllerConfig(BaseModel):
    states: List[ControllerStateConfig] = Field(default_factory=list)
    off_duration: Optional[OffDuration] = None
    sleep_state: Optional[ControllerStateConfig] = None

    @classmethod
    def from_yaml(cls: Self, yaml_path: Path) -> Self:
        yaml_path = Path(yaml_path)
        with yaml_path.open('r') as f:
            for appname, app_cfg in yaml.load(f, Loader=yaml.SafeLoader).items():
                if app_cfg['class'] == 'RoomController':
                    return cls.model_validate(app_cfg)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        table = Table(
            Column('Time', width=15),
            Column('Scene'),
            highlight=True,
            padding=1,
            collapse_padding=True,
        )
        for state in self.states:
            scene_json = state.to_apply_kwargs()
            lines = [
                f'{name:20}{state["state"]}   Brightness: {state["brightness"]:<4}  Temp: {state["color_temp"]}'
                for name, state in scene_json['entities'].items()
            ]
            table.add_row(state.time.strftime('%I:%M:%S %p'), '\n'.join(lines))
        yield table

    def sort_states(self):
        """Should only be called after all the times have been resolved"""
        assert all(
            isinstance(state.time, time) for state in self.states
        ), 'Times have not all been resolved yet'
        self.states = sorted(self.states, key=lambda s: s.time, reverse=True)

    def current_state(self, now: time) -> ControllerStateConfig:
        self.sort_states()
        for state in self.states:
            if state.time <= now:
                return state
        else:
            return self.states[0]

    def current_scene(self, now: time) -> Dict:
        state = self.current_state(now)
        return state.scene

    def current_off_duration(self, now: time) -> timedelta:
        state = self.current_state(now)
        if state.off_duration is None:
            if self.off_duration is None:
                raise ValueError('Need an off duration')
            else:
                return self.off_duration
        else:
            return state.off_duration


class ButtonConfig(BaseModel):
    app: str
    button: str | List[str]
    ref_entity: str
