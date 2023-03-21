ScriptName = "@name"
Description = "@description"
Creator = "@author"
Version = "@version"
Website = None

DOCK_COMMONS_NAME = "@dock_common_module"
SHIM_NAME = "@shim_name"

# XXX business end

import os
import codecs
import json

try:
    dock_commons = __import__(DOCK_COMMONS_NAME)
except:
    dock_commons = None
UI_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "UI_Config.json")
UI_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "shim-ui-settings.json")

DEBUG_BUTTONS = ("__dock_reload",)

delayed_settings_upload = None
delayed_initial_state = None

def button_pressed_internal(function, name):
    global dock_commons
    if dock_commons is None:
        dock_commons = __import__(DOCK_COMMONS_NAME)

    dock_commons.button(SHIM_NAME, function, name)

def add_button(function, name):
    globals()[function] = lambda: button_pressed_internal(function, name)

def Init():
    global delayed_settings_upload
    if os.path.exists(UI_CONFIG_FILE):
        with codecs.open(UI_CONFIG_FILE, encoding="utf-8") as f:
            config = json.load(f)

        if os.path.exists(UI_SETTINGS_FILE):
            with codecs.open(UI_SETTINGS_FILE, encoding="utf-8-sig") as f:
                settings = json.load(f)

        else:
            settings = {}

        for name, item in config.items():
            if name == "output_file":
                continue

            if item["type"] == "button":
                add_button(item["function"], name)

        base_settings = {name: x["value"] for name, x in config.items() if "value" in x}
        base_settings.update(settings)

        delayed_settings_upload = base_settings

def Tick():
    global delayed_settings_upload, delayed_initial_state, dock_commons
    if dock_commons is None:
        try:
            dock_commons = __import__(DOCK_COMMONS_NAME)
        except:
            return

    if delayed_settings_upload is not None:
        dock_commons.initial_settings(SHIM_NAME, delayed_settings_upload)
        delayed_settings_upload = None

    if delayed_initial_state:
        dock_commons.initial_state(SHIM_NAME, delayed_initial_state)
        delayed_initial_state = None

def Execute(data):
    pass

def ReloadSettings(data):
    dock_commons.settings_reloaded(SHIM_NAME, data)

def ScriptToggled(state):
    if dock_commons is not None:
        dock_commons.script_toggled(SHIM_NAME, state)
    else:
        global delayed_initial_state
        delayed_initial_state = state


