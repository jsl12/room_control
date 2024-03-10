from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Dict, List, Self

import yaml
from astral import SunDirection
from pydantic import BaseModel, BeforeValidator, ValidationError, conint, root_validator


def str_to_timedelta(input_str: str) -> timedelta:
    try:
        hours, minutes, seconds = map(int, input_str.split(':'))
        return timedelta(hours=hours, minutes=minutes, seconds=seconds)
    except Exception:
        return timedelta()
    

def str_to_direction(input_str: str) -> SunDirection:
    if input_str.lower() == 'setting':
        return SunDirection.SETTING
    elif input_str == 'rising':
        return SunDirection.RISING
    else:
        raise ValidationError(f'Invalid sun direction: {input_str}')


OffDuration = Annotated[timedelta, BeforeValidator(str_to_timedelta)]


class State(BaseModel):
    state: bool = True
    brightness: conint(ge=1, le=255) = None
    color_temp: conint(ge=200, le=650) = None


class ApplyKwargs(BaseModel):
    """Arguments to call with the 'scene/apply' service"""

    entities: Dict[str, State]
    transition: int = None


class ControllerStateConfig(BaseModel):
    time: str | datetime = None
    elevation: float = None
    direction: Annotated[SunDirection, BeforeValidator(str_to_direction)] = None
    off_duration: OffDuration = None
    scene: Dict[str, State]

    @root_validator(pre=True)
    def check_args(cls, values):
        time, elevation = values.get('time'), values.get('elevation')
        if time is None and elevation is None:
            raise ValueError('Either time or elevation must be set.')
        elif time is not None and elevation is not None:
            raise ValueError('Only one of time or elevation can be set.')
        elif elevation is not None:
            assert 'direction' in values
        return values

    def to_apply_kwargs(self, transition: int = 0):
        return ApplyKwargs(entities=self.scene, transition=transition).model_dump(exclude_none=True)


class RoomConfig(BaseModel):
    states: List[ControllerStateConfig]
    off_duration: OffDuration = None

    @classmethod
    def from_yaml(cls: Self, yaml_path: Path):
        yaml_path = Path(yaml_path)
        with yaml_path.open('r') as f:
            for appname, app_cfg in yaml.load(f, Loader=yaml.SafeLoader).items():
                if app_cfg['class'] == 'RoomController':
                    break
        print(app_cfg)
        return cls(**app_cfg)
