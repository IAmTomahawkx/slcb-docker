import asyncio
import sys

import pkg_resources
import logging

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

async def main():
    logger.info(f"Initializing docker (A: proto@{version})")
    logger.debug("Running on python %s", sys.version)
    logger.debug("Running on aiohttp %s", pkg_resources.get_distribution("aiohttp").version)
    logger.debug("Running on ujson %s", pkg_resources.get_distribution("ujson").version)

    http = HTTPHandler(None) # type: ignore
    manager = PluginManager(http)
    http.manager = manager # circular arguments, so do this and tell the type checker to take a hike

    await http.setup()
    await http.start_service(debug=False)
    try:
        await http.wait_for_pingpong(timeout=10)
    except asyncio.TimeoutError:
        logger.debug("Timeout reached waiting for pingpong. Aborting startup")
        await http.end_service(error=False)
        return

    if http.auth_state != AuthState.AuthOK:
        logger.debug(f"Entered bad auth state {http.auth_state.name} ({http.auth_state.value}). Aborting startup")
        await http.end_service(error=False)
        return

    # preflight load or wait for script to send load payloads?
