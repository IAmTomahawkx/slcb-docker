# This file will only trigger if it detects the dock is not installed.
import codecs
import os
import json
import re
import shutil
import clr
import zipfile

try:
    clr.AddReference("System.Windows.Forms")
except: pass
from System.Windows.Forms.MessageBox import Show
clr.AddReference("System.Net.Http")
clr.AddReference("System.IO")
from System.IO import BinaryWriter, File, FileMode
from System.Net.Http import HttpClient

ScriptName = "WraptorService"
Description = "Wraptor installer for the Script Dock"
Creator = "TMHK"
Version = "0.1.0"
Website = None

msgbox = lambda obj: Show(str(obj))
is_tested = False
Parent = None
base_url = "http://127.0.0.1:1006/"
DOWNLOAD_URL = "https://github.com/IAmTomahawkx/slcb-docker/archive/refs/heads/master.zip" # use master until a release is ready
SEARCH_FOR_DIR = "TMHK-docker"

version_re = re.compile(r"(?:(?P<pre_restriction>>=?|<=?)?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+))|\*")

def Init():
    pass

def Execute(data):
    pass

def Tick():
    global is_tested
    if not is_tested:
        is_tested = True
        try:
            version = test_for_dock()
            if version is None or not version_meets_constraints(version):
                install_dock()
                #eradicate_self()
                msgbox("Please reload the scripts tab to complete load of the plugin dock")
        except RuntimeError as e:
            msgbox(e.args[0])
            return

def parse_version_string(version):
    """
    takes a version string and strips it of any alpha/rc markers, and returns the version as a tuple of int, int, int.
    :param version:
    :type version: str
    :return: tuple[int, int, int]
    """
    v = version.strip("abcr")
    ver = tuple(int(x) for x in v.split("."))
    if len(ver) != 3:
        raise ValueError("Bad version string")

    return ver

def version_meets_constraints(version):
    with codecs.open(os.path.join(os.path.dirname(__file__), "plugin.json"), encoding="utf-8") as f:
        data = json.load(f)

    if "required_dock_version" not in data:
        return True # any version allowed

    required = data["required_dock_version"]
    if isinstance(required, str): # only minimum version
        return parse_version_string(required) <= version
    else:
        min_req, max_req = parse_version_string(required[0]), parse_version_string(required[1])
        return min_req <= version <= max_req

def test_for_dock():
    Parent.Log(ScriptName, "Checking for running dock at {}".format(base_url))
    response = Parent.GetRequest(base_url + "version", {})
    response = json.loads(response)
    if "response" in response: # dock is active and running, check version
        data = json.loads(response["response"])
        version = data["version"]
        comp_ver = tuple(data["comparable_version"])

        Parent.Log(ScriptName, "Found running dock with version {}".format(version))
        return comp_ver

    else:
        Parent.Log(ScriptName, "Did not find running dock, checking scripts folder")
        pth = os.path.dirname(os.path.dirname(__file__))
        paths = os.listdir(pth)
        if SEARCH_FOR_DIR in paths:
            try:
                with codecs.open(os.path.join(pth, SEARCH_FOR_DIR, "DockMain_StreamlabsSystem.py"), encoding="utf-8") as f:
                    file = f.read()
            except:
                return

            Parent.Log(ScriptName, "Found DockMain, checking version")
            version = re.search(r"Version = \"(?P<version>\d+\.\d+\.\d+)", file)
            if not version:
                Parent.Log(ScriptName, "No version found, conflict detected (force user to manually install)")
                raise RuntimeError("An existing dock install has been detected, but is not running, and it's version cannot be determined. "
                                   "If you have manually modified the dock code, please undo your changes. Otherwise, please contact support for the dock.")

            v = version.group("version")
            return parse_version_string(v)

        Parent.Log(ScriptName, "Dock not found in scripts folder")

def install_dock():
    target = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), SEARCH_FOR_DIR))
    Parent.Log(ScriptName, "Installing dock to {}".format(target))
    zip_location = pull_zip()
    temp_location = extract_zip(zip_location)
    import time
    time.sleep(8)
    install_zip(temp_location, target)

def pull_zip():
    TEMP = os.environ["TEMP"]
    target = os.path.join(TEMP, "TMHKDOCKER-inst.zip")

    client = HttpClient()
    t = client.GetStreamAsync(DOWNLOAD_URL)
    t.Wait()
    zipdata = t.Result
    Parent.Log(ScriptName, str(type(zipdata)))

    #File.WriteAllBytes(target, zipdata.ToArray())

    writer = File.Open(target, FileMode.Create)
    zipdata.CopyTo(writer)
    writer.Flush()
    writer.Dispose()
    client.Dispose()
    return target

def extract_zip(location):
    TEMP = os.environ["TEMP"]
    target = os.path.join(TEMP, "TMHKDOCKER-inst")

    if os.path.exists(target):
        os.rmdir(target)

    file = zipfile.ZipFile(location)
    file.extractall(target)
    file.close()

    for x in os.listdir(target):
        for file in os.listdir(os.path.join(target, x)):
            shutil.move(os.path.join(target, x, file), os.path.join(target, file))

    return target

def install_zip(exec_target, install_target):
    os.system("py {}\\install.py \"{}\"".format(exec_target, install_target))

def eradicate_self():
    # we need to get rid of this file before the dock loads up and tries to onboard the devs plugin
    os.remove(__file__)