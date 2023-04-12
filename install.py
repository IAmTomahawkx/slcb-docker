# This file is meant to be automatically run by a participating script
import json
import os
import re
import shutil
import sys
import subprocess


def find_chatbot_folder() -> str:
    return f"{os.environ['LOCALAPPDATA']}\\Streamlabs\\Streamlabs Chatbot\\" # TODO

def find_suitable_python_install() -> str | None:
    proc = subprocess.Popen(["py", "-0p"], stdout=-1)
    proc.wait(1)
    proc.stdout.seek(0)
    data = proc.stdout.read().decode()
    if data.startswith("'"):
        raise RuntimeError(f"Python is not installed on this machine(?)\nGot the following from the py prompt:\n{data}")

    matches = re.findall(r"-(?P<major>\d)\.(?P<minor>\d)(?:-32|-64)?\s*(?P<path>[^*\n\r\t]+)", data)
    if not matches:
        raise RuntimeError(f"No python installations found: Got:\n{data}")

    highest = max(matches, key=lambda k: (int(k[0]), int(k[1])))
    if highest[0:1] < (3, 10):
        raise RuntimeError("Could not find a python install 3.10 or higher")

    return highest[2]

def main():
    if sys.version_info < (3, 10):
        executable = find_suitable_python_install()
    else:
        executable = sys.executable

    #folder = find_chatbot_folder()
    current = os.path.dirname(__file__)
    target = sys.argv[1]
    with open(os.path.join(current, "TMHK-docker", "settings.json"), "w") as f:
        json.dump({"310_executable": executable, "is_debug": False}, f)

    shutil.copytree(os.path.join(current, "TMHK-docker"), target)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_last()
        print("That's an error. Please take a screenshot of this and send it to the dock devs, and then press enter a few times to make this go away")
        input()