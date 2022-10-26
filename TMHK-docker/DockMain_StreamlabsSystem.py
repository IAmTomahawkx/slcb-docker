import codecs
import json
import os
import sys
import time
import random as _random
import logging
import traceback
from System.Windows.Forms.MessageBox import Show

random = _random.WichmannHill()  # noqa
sys.platform = "win32"  # fixes the bot setting platform to `cli`, which breaks subprocess
import subprocess

if False:
    Parent = object()  # noqa

ScriptName = "Dock Hub"
Description = "Manages the plugin Dock"
Creator = "TMHK"
Version = "0.1.0a"
Website = None

msgbox = lambda obj: Show(str(obj))

DIR_PATH = os.path.abspath(os.path.dirname(__file__))
BOT_SETTINGS_PATH = os.path.join(DIR_PATH, "settings.json")
STAMP_PATH = os.path.join(DIR_PATH, "client.lock")
DAEMON_PATH = os.path.join(DIR_PATH, "daemon")
DAEMON_LOCKFILE = os.path.join(DAEMON_PATH, "daemon.lock")
RESTART_FILE = os.path.join(DIR_PATH, "restart.lock")
LOG_FILE = os.path.join(DIR_PATH, "script.log")

if os.path.exists(BOT_SETTINGS_PATH):
    with codecs.open(BOT_SETTINGS_PATH, encoding="utf-8-sig") as f:
        settings = json.load(f)

else:
    settings = {
        "is_debug": True,
        "310_executable": "%USERPROFILE%\AppData\Local\Programs\Python\Python310\Python.exe"
    }

if os.path.exists(STAMP_PATH):
    os.remove(STAMP_PATH)

# XXX logging

try:
    unicode  # noqa
    _has_unicode = True
except NameError:
    _has_unicode = False


class BufferedStreamHandler(logging.StreamHandler):
    stream_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
                                         "%Y-%m-%d %H:%M:%S")  # noqa
    bot_formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")  # noqa

    def __init__(self, stream):
        logging.StreamHandler.__init__(self, stream)
        self.buffer = []

    def _emit(self, record):
        """
        Emit a record.

        If a formatter is specified, it is used to format the record.
        The record is then written to the stream with a trailing newline.  If
        exception information is present, it is formatted using
        traceback.print_exception and appended to the stream.  If the stream
        has an 'encoding' attribute, it is used to determine how to do the
        output to the stream.
        """
        try:
            msg = self.stream_formatter.format(record)
            stream = self.stream
            fs = "%s\n"
            if not _has_unicode:
                stream.write(fs % msg)
            else:
                try:
                    if (isinstance(msg, unicode) and
                            getattr(stream, 'encoding', None)):
                        ufs = u'%s\n'
                        try:
                            stream.write(ufs % msg)
                        except UnicodeEncodeError:
                            # Printing to terminals sometimes fails. For example,
                            # with an encoding of 'cp1251', the above write will
                            # work if written to a stream opened or wrapped by
                            # the codecs module, but fail when writing to a
                            # terminal even when the codepage is set to cp1251.
                            # An extra encoding step seems to be needed.
                            stream.write((ufs % msg).encode(stream.encoding))
                    else:
                        stream.write(fs % msg)
                except UnicodeError:
                    stream.write(fs % msg.encode("UTF-8"))
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)

    def emit(self, record):
        try:
            if settings["is_debug"] or record.levelno > logging.DEBUG:
                msg = self.bot_formatter.format(record)
                Parent.Log(record.name, msg)
        except NameError:
            pass  # case when Parent isn't in existence yet

        # self.buffer.append(record)
        self._emit(record)
        self.flush()

    def flush(self):
        if self.buffer:
            for record in self.buffer:
                self._emit(record)

        logging.StreamHandler.flush(self)

    def close(self):
        self.acquire()
        self.flush()
        try:
            self.stream.close()
        except AttributeError:
            pass
        logging.Handler.close(self)
        self.release()


logger = logging.getLogger("dock")
logger.setLevel(logging.DEBUG)
logger_http = logging.getLogger("dock.http")
logger_http.setLevel(logging.DEBUG)
_logging_handler = BufferedStreamHandler(codecs.open(LOG_FILE, mode="w", encoding="UTF-8"))
_logging_handler.setLevel(logging.DEBUG)
logger.addHandler(_logging_handler)
logger_http.addHandler(_logging_handler)


def _logging_flush():
    _logging_handler.flush()


# XXX state management

class AuthState(object):
    WaitingForInit = 0
    PendingPingPong = 1
    PingPongFailed = 2
    ClientServerMismatch = 3
    AuthOK = 4
    Closing = 5


class _State(object):
    def __init__(self):
        self.auth_state = AuthState.WaitingForInit
        self.last_stamp = time.time()
        self.last_poll = time.time()
        self.auth = None
        self.killcode = None
        self.process = None

        if os.path.exists(RESTART_FILE):
            with codecs.open(RESTART_FILE, encoding="utf-8") as f:
                data = json.load(f)
                if time.time() - data["t"] >= 60:
                    return

                self.auth = data["auth"]
                self.killcode = data["killcode"]

            os.remove(RESTART_FILE)

state = _State()

def write_stamp(t):
    """
    Writes the current timestamp to the lockfile. This needs to be called at least every 30 seconds, or the daemon will shut down
    :param t: the current timestamp.
    :type t: int
    :return: None
    """
    with codecs.open(STAMP_PATH, mode="w", encoding="utf-8") as f:
        f.write(str(t))

    state.last_stamp = t

# XXX HTTP request management

def get_request(route):
    """
    Sends a raw GET request to the daemon. Sanity checks are not done here, if auth is not complete this request will bounce
    :param route: The route to request from. Does not need a leading /
    :type route: str
    :return: dict[Literal["error"], str] | dict[str, Any] | None
    """
    if route != "outbound":
        logger_http.debug("Sending request to route %s ", route)

    resp = Parent.GetRequest("http://127.0.0.1:1006/" + route.strip("/"), {"Authorization": state.auth})
    data = json.loads(resp)
    if route != "outbound":
        logger_http.debug("Received response from %s with status %s", route, data["status"])

    if data["status"] == 204:
        return None

    elif 200 <= data["status"] <= 299:
        payload = json.loads(data["response"])
        return payload

    else:
        return data["error"]

def post_request(route, payload):
    """
    Sends a POST request to the daemon. Sanity checks are not done here.
    :param route: The route to request. Does not need a leading /
    :type route: str
    :param payload: The payload body. must be a dict
    :return: dict[Literal["error"], str] | dict[str, Any] | None
    """
    if route != "inbound":
        logger_http.debug("Sending request to route %s ", route)

    resp = Parent.PostRequest("http://127.0.0.1:1006/" + route.strip("/"), {"Authorization": state.auth}, payload, True)
    data = json.loads(resp)
    if route != "inbound":
        logger_http.debug("Received response from %s with status %s", route, data["status"])

    if data["status"] == 204:
        return None

    elif 200 <= data["status"] <= 299:
        Parent.Log(ScriptName, str(data["response"]))
        payload = json.loads(data["response"])
        return payload

    else:
        Parent.Log(ScriptName + "err", str(data))
        return data["error"]

# XXX daemon management

def _generate_auth():
    import string
    opts = string.ascii_letters + string.digits
    return "".join([random.choice(opts) for _ in range(32)])

def _daemon_startup():
    state.auth = _generate_auth()
    for i in range(5):
        response = post_request("auth", {"code": state.auth})
        if isinstance(response, dict) and "challenge" in response:
            break
        else:
            time.sleep(0.5)
            continue

    if isinstance(response, dict) and "challenge" in response:
        resp = post_request("pingpong", {"challenge": response["challenge"]})
        if resp is None:
            state.auth_state = AuthState.AuthOK
        else:
            state.auth_state = AuthState.PingPongFailed
    else:
        state.auth_state = AuthState.ClientServerMismatch

    if state.auth_state != AuthState.AuthOK:
        get_request("kill?code=%s&graceful=0" % state.killcode)
        return False

    return True

def check_no_daemon():
    if os.path.exists(DAEMON_LOCKFILE):
        logger.debug("Found daemon lockfile")
        with codecs.open(DAEMON_LOCKFILE, mode="r", encoding="UTF-8") as f:
            timestamp = f.read().strip()

        try:
            timestamp = int(timestamp)
        except ValueError:
            logger.debug("Daemon lockfile has bad data, ignoring")
        else:
            if timestamp < int(time.time()) - 30:
                logger.warning("Daemon lockfile has valid timestamp, refusing call to start daemon")
                return False
            else:
                logger.debug("Daemon lockfile has invalid timestamp, ignoring")

    return True

def start_daemon():
    logger.debug("Starting daemon; checking lockfile")
    if not check_no_daemon():
        return

    _start_daemon()

def _start_daemon(level=0):
    state.killcode = _generate_auth()
    try:
        args = [
            settings["310_executable"].replace("%USERPROFILE%", os.environ["USERPROFILE"]),
            os.path.join(DAEMON_PATH, "init.py"),
            state.killcode
        ]
        Parent.Log("reee", str(args))
        state.process = subprocess.Popen(
            args=args,
            cwd=DAEMON_PATH,
            # env={"ENABLE_VIRTUAL_TERMINAL_PROCESSING": "1"}
        )
    except Exception as e:
        Parent.Log(ScriptName, traceback.format_exc())
    if not _daemon_startup():
        logger.debug("PingPong failed. Attempting restart")
        state.process.wait()
        if level > 2:
            return
        # _start_daemon(level+1)

def poll_daemon(t):
    if state.auth_state != AuthState.AuthOK:
        state.last_poll = t
        return

    resp = get_request("outbound")
    if resp == "An error occurred while sending the request.":
        logger.error("Failed to fetch.")
        return

    if not isinstance(resp, list):
        logger.error("Unexpected %s of type %s, expected list from daemon poll response", str(resp), repr(type(resp)))
        return

    response = []
    for event in resp:
        data = event['data']
        attr = getattr(Parent, data["type"], None)
        if not attr:
            response.append(
                {"nonce": event["nonce"], "response": None, "error": "Unable to find Event Type %s" % data["type"]})
        else:
            response.append({"nonce": event["nonce"], response: attr(*data["args"]), "error": None})

    if response:
        post_request("inbound", {"response": response})

    state.last_poll = t

def graceful_kill_daemon():
    # called from the ui tab
    logger.info("Received UI order to shut down daemon (graceful)")
    _kill_daemon()

def ungraceful_kill_daemon():
    # called from ui tab
    logger.info("Received UI order to shut down daemon (ungraceful)")
    _kill_daemon(False)

def _kill_daemon(graceful=True):
    resp = get_request("kill?code=%s&graceful=%i" % (state.killcode, int(graceful)))
    if resp is not None:
        msgbox("Failed to kill the dock. Consider doing it from the process manager. (dock said: %s)" % str(resp))

# XXX serializing

def serialize_data_payload(data):
    if data.IsWhisper():
        if data.IsFromTwitch():
            source = 3
        else:
            source = 4
    else:
        if data.IsFromTwitch():
            source = 0
        elif data.IsFromDiscord():
            source = 1
        else:
            source = 2

    return {
        "userid": data.User,
        "username": data.UserName,
        "message": data.Message,
        "is_chat": data.IsChatMessage(),
        "raw_data": data.RawData,
        "is_raw": data.IsRawData(),
        "source": source,
        "service_type": data.ServiceType
    }


# XXX bot stuff

def Init():
    write_stamp(int(time.time()))
    if state.auth:
        t = get_request("authcheck")
        if t == "An error occurred while sending the request.":  # daemon isnt running
            start_daemon()
        elif t is None:  # we still have auth after reload
            logger.info("Successfully re-authenticated after reload")
            state.auth_state = AuthState.AuthOK
        else:
            Parent.SendStreamMessage("Failed to connect to the daemon!")
            logger.critical(
                "Unable to connect to daemon. Invalid auth. Please manually kill the daemon process and try again")
    else:
        start_daemon()

def Tick():
    now = int(time.time())
    if now - state.last_stamp > 30:
        write_stamp(now)

    if now - state.last_poll > 1:
        poll_daemon(now)

def Execute(data):
    post_request("inbound/parse", {"type": 0, "data": serialize_data_payload(data)})

def Unload():
    logger.info("Received UNLOAD from bot")
    _logging_handler.close()
    with codecs.open(RESTART_FILE, mode="w", encoding="UTF-8") as f:
        json.dump({
            "t": int(time.time()),
            "auth": state.auth,
            "killcode": state.killcode
        }, f)

def ScriptToggled(script_state):
    if not script_state:
        warning = "You appear to have disabled the dock script. " \
                  "Doing so prevent any scripts being run through the dock from being handled. " \
                  "You should probably turn the it back on."
        msgbox(warning)
    else:
        if time.time() - state.last_poll > 10:  # We need to check if the daemon died from the script being disabled
            logger.warning("Script has been toggled OFF for more than 10 seconds. Checking if daemon has died")
            resp = get_request("authcheck")
            if resp is not None:
                logger.warning("Unable to authenticate with daemon after script toggle. Attempting to start new daemon")
                start_daemon()
            else:
                logger.info("Successful authentication after script toggle")
