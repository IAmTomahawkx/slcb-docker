import codecs
import json
import os
import sys
import secrets
import time
import random as _random
import logging

random = _random.WichmannHill() # noqa
sys.platform = "win32" # fixes the bot setting platform to `cli`, which breaks subprocess
import subprocess

if False:
    Parent = object() # noqa

ScriptName = "Dock Hub"
Description = "Manages the plugin Dock"
Creator = "TMHK"
Version = "0.1.0a"

if version.endswith(('a', 'b', 'rc')):
    # append version identifier based on commit count
    try:
        p = subprocess.Popen(['git', 'rev-list', '--count', 'HEAD'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        if out:
            version += out.decode('utf-8').strip()
        p = subprocess.Popen(['git', 'rev-parse', '--short', 'HEAD'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        if out:
            version += '+g' + out.decode('utf-8').strip()
    except Exception:
        pass

DIR_PATH = os.path.abspath(os.path.dirname(__file__))
BOT_SETTINGS_PATH = os.path.join(DIR_PATH, "settings.json")
STAMP_PATH = os.path.join(DIR_PATH, "client.lock")
DAEMON_PATH = os.path.join(os.path.dirname(DIR_PATH), "daemon") # TODO: determine where daemon folder should go
DAEMON_LOCKFILE = os.path.join(DAEMON_PATH, "daemon.lock")
RESTART_FILE = os.path.join(DIR_PATH, "restart.lock")
LOG_FILE = os.path.join(DIR_PATH, "script.log")

if os.path.exists(BOT_SETTINGS_PATH):
    with codecs.open(BOT_SETTINGS_PATH, encoding="utf-8-sig") as f:
        settings = json.load(f)

else:
    settings = {
        "is_debug": True,
        "310_executable": ""
    }

if os.path.exists(STAMP_PATH):
    os.remove(STAMP_PATH)

# XXX logging

try:
    unicode # noqa
    _has_unicode = True
except NameError:
    _has_unicode = False

class BufferedStreamHandler(logging.StreamHandler):
    stream_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S") # noqa
    bot_formatter = logging.Formatter("[%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S") # noqa

    def __init__(self, stream):
        logging.StreamHandler.__init__(stream)
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
                            #Printing to terminals sometimes fails. For example,
                            #with an encoding of 'cp1251', the above write will
                            #work if written to a stream opened or wrapped by
                            #the codecs module, but fail when writing to a
                            #terminal even when the codepage is set to cp1251.
                            #An extra encoding step seems to be needed.
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
            pass # case when Parent isn't in existence yet

        self.buffer.append(record)

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
logger_http = logging.getLogger("dock.http")
_logging_handler = BufferedStreamHandler(codecs.open(LOG_FILE))
logger.addHandler(_logging_handler)

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
        self.last_stamp = None
        self.last_poll = None
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
    logger_http.debug("Sending request to route %s ", route)
    resp = Parent.GetRequest("http://127.0.0.1:1006/" + route.strip("/"), {"Authorization": state.auth})
    data = json.loads(resp)
    logger_http.debug("Received response from %s with status %s", route, data["status"])

    if data["status"] == 204:
        return None

    elif 200 <= data["status"] <= 299:
        payload = json.loads(resp["response"])
        return payload

    else:
        return resp["error"]

def post_request(route, payload):
    """
    Sends a POST request to the daemon. Sanity checks are not done here.
    :param route: The route to request. Does not need a leading /
    :type route: str
    :param payload: The payload body. must be a dict
    :return: dict[Literal["error"], str] | dict[str, Any] | None
    """
    logger_http.debug("Sending request to route %s ", route)
    resp = Parent.PostRequest("http://127.0.0.1:1006/" + route.strip("/"), {"Authorization": state.auth}, payload, True)
    data = json.loads(resp)
    logger_http.debug("Received response from %s with status %s", route, data["status"])

    if data["status"] == 204:
        return None

    elif 200 <= data["status"] <= 299:
        payload = json.loads(resp["response"])
        return payload

    else:
        return resp["error"]

# XXX daemon management

def _daemon_startup():
    state.auth = secrets.token_urlsafe(8)
    response = post_request("auth", {"code": state.auth})
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

def _start_daemon():
    state.killcode = secrets.token_urlsafe(8)
    state.process = subprocess.Popen(args=[os.path.join(DAEMON_PATH, "init.py"), state.killcode], executable=settings["310_executable"].replace("%USERPROFILE%", os.environ["USERPROFILE"]))
    if not _daemon_startup():
        logger.debug("PingPong failed. Attempting restart")
        state.process.wait()
        _start_daemon()

def poll_daemon(t):
    if state.auth_state != AuthState.AuthOK:
        state.last_poll = t
        return

    resp = get_request("outbound")
    if not isinstance(resp, list):
        logger.error("Unexpected %s, expected list from daemon poll response", repr(type(resp)))
        return

    response = []
    for event in resp:
        data = event['data']
        attr = getattr(Parent, data["type"], None)
        if not attr:
            response.append({"nonce": event["nonce"], "response": None, "error": "Unable to find Event Type %s" % data["type"]})
        else:
            response.append({"nonce": event["nonce"], response: attr(*data["args"]), "error": None})

    post_request("inbound", {"response": response})

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
        if get_request("auth-check") is not None:
            pass # TODO: figure out what to do if our auth is rejected on startup
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