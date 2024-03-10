from typing import Dict

from pydantic import (
    BaseModel,
    ValidationError,
    field_validator,
)


def validate_int(v):
    if not len(bytes(v)) == 1:
        raise ValidationError()


class State(BaseModel):
    state: bool = True
    brightness: int = None
    color_temp: int = None

    @field_validator('brightness')
    @classmethod
    def validate_brightness(cls, v: int) -> int:
        assert 0 <= v <= 255
        return v

    @field_validator('color_temp')
    @classmethod
    def validate_color_temp(cls, v: int) -> int:
        assert 200 <= v <= 600
        return v


# Scene = RootModel[Dict[str, State]]


class ApplyScene(BaseModel):
    entities: Dict[str, State]
    transition: int = None
