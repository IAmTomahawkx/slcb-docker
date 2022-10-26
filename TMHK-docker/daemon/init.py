import asyncio
import os
import sys

import pkg_resources
import logging

try:
    import ujson, aiohttp
except ModuleNotFoundError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "ujson", "aiohttp"])

from daemon.manager import PluginManager
from daemon.http import HTTPHandler
from daemon.enums import AuthState

logger = logging.getLogger("dock.init")

version = "0.1.0a"

if version.endswith(('a', 'b', 'rc')):
    # append version identifier based on commit count
    try:
        import subprocess
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

class _ColourFormatter(logging.Formatter):
    """
    This class is used from the `discord.py` library, and is licensed under the MIT License.
    """

    # ANSI codes are a bit weird to decipher if you're unfamiliar with them, so here's a refresher
    # It starts off with a format like \x1b[XXXm where XXX is a semicolon separated list of commands
    # The important ones here relate to colour.
    # 30-37 are black, red, green, yellow, blue, magenta, cyan and white in that order
    # 40-47 are the same except for the background
    # 90-97 are the same but "bright" foreground
    # 100-107 are the same as the bright ones but for the background.
    # 1 means bold, 2 means dim, 0 means reset, and 4 means underline.

    LEVEL_COLOURS = [
        (logging.DEBUG, '\x1b[37;1m'),
        (logging.INFO, '\x1b[34;1m'),
        (logging.WARNING, '\x1b[33;1m'),
        (logging.ERROR, '\x1b[31m'),
        (logging.CRITICAL, '\x1b[41m'),
    ]

    FORMATS = {
        level: logging.Formatter(
            f'\x1b[30;1m%(asctime)s\x1b[0m {colour}%(levelname)-8s\x1b[0m \x1b[35m%(name)s\x1b[0m %(message)s',
            '%Y-%m-%d %H:%M:%S',
        )
        for level, colour in LEVEL_COLOURS
    }

    def format(self, record):
        formatter = self.FORMATS.get(record.levelno)
        if formatter is None:
            formatter = self.FORMATS[logging.DEBUG]

        # Override the traceback to always print in red
        if record.exc_info:
            text = formatter.formatException(record.exc_info)
            record.exc_text = f'\x1b[31m{text}\x1b[0m'

        output = formatter.format(record)

        # Remove the cache layer
        record.exc_text = None
        return output


def setup_logging():
    _logger = logging.getLogger("dock")
    handler = logging.StreamHandler()

    if (hasattr(handler.stream, "isatty") and handler.stream.isatty()) and any(x in os.environ for x in ["ANSICON", "WT_SESSION", "PYCHARM_HOSTED"]):
        formatter = _ColourFormatter()
    else:
        dt_fmt = '%Y-%m-%d %H:%M:%S'
        formatter = logging.Formatter('[{asctime}] [{levelname:<8}] {name}: {message}', dt_fmt, style='{')

    handler.setFormatter(formatter)
    _logger.setLevel(logging.DEBUG)
    _logger.addHandler(handler)

async def main():
    logger.info(f"Initializing Streamlabs Chatbot Dock (A: proto@{version})")
    logger.debug("Running on python %s", sys.version)
    logger.debug("Running with aiohttp %s", pkg_resources.get_distribution("aiohttp").version)
    logger.debug("Running with ujson %s", pkg_resources.get_distribution("ujson").version)

    http = HTTPHandler(None) # type: ignore
    manager = PluginManager(http)
    http.manager = manager # circular arguments, so do this and tell the type checker to take a hike

    await http.setup()
    await http.start_service(debug=True)
    try:
        await http.wait_for_pingpong(timeout=10)
    except asyncio.TimeoutError:
        http.auth_state = AuthState.PingPongFailed
        logger.debug("Timeout reached waiting for pingpong. Aborting startup")
        await http.end_service(error=False)
        return

    if http.auth_state != AuthState.AuthOK:
        logger.debug(f"Entered bad auth state {http.auth_state.name} ({http.auth_state.value}). Aborting startup")
        await http.end_service(error=False)
        return

    # preflight load or wait for script to send load payloads?

if __name__ == "__main__":
    setup_logging()
    asyncio.run(main())
    input()