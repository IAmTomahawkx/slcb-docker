from types import ModuleType
from typing import TYPE_CHECKING, Awaitable, Callable, Literal, TypedDict

from typing_extensions import NotRequired

if TYPE_CHECKING:
    from ..interface import Interface


class UIConfigValue(TypedDict, final=False):
    title: str
    tooltip: str
    group: str
    type: Literal["textbox", "numberbox", "checkbox", "slider", "dropdown"]


class TextBoxValue(UIConfigValue):
    value: str


class NumberBoxValue(UIConfigValue):
    value: int


class CheckBoxValue(UIConfigValue):
    value: bool


class SliderValue(UIConfigValue):
    min: int
    max: int
    ticks: int
    value: int


class DropdownValue(UIConfigValue):
    items: list[str]
    value: str


UIConfig = dict[str, TextBoxValue | NumberBoxValue | CheckBoxValue | SliderValue | DropdownValue]


class Config(TypedDict):
    name: str
    description: str
    author: str
    version: str

    dock_version: NotRequired[str]
    ui_config: NotRequired[UIConfig]


class PluginModule(ModuleType):
    init: Callable[[Interface], Awaitable[None]]
