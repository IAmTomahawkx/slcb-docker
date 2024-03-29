[![development status | 2 - Pre-Alpha](https://img.shields.io/badge/Development%20Status-2%20--%20Pre%20Alpha-red)](https://pypi.org/classifiers/)
[![code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
![license](https://img.shields.io/github/license/IAmTomahawkx/slcb-docker)
___
<h1 align="center">
The Dock
</h1>
<p align="center">
<sup>
Run your plugins in a modern python version, instead of 2.7
</sup>
</p>

___
This script acts as a wrapper around the Streamlabs Chatbot, allowing you to program in a modern, fully typed environment.
No more unresolved `Parent` variable, no more being unable to do networking. You'll be able to program normally, in an async environment.

## How do I use this?
Currently, this software is unstable and in pre-alpha. I have not made release copies which can easily be installed.
That being said, you can install this manually by cloning the repository and copying the TMHK-docker folder into your bots Scripts folder.
Alternatively, attempting to install any plugin that has been properly bundled will result in the latest commit on the master branch being installed automatically.

## Roadmap
Here are a list of things that I will be implementing. Checked boxes mean it is currently implemented

- [x] Base daemon with poll+response capabilities
- [x] Create shim scripts in the bot for active representation of each plugin (including UI)
- [ ] Create plugin interface which retains the functionality of the Chatbot interface, while also introducing modern practices
- [x] Ability to use the `Parse` method
- [ ] Fully implement core of the Parent method (excluding cooldowns and obs, these should be implemented separately inside the dock)
- [ ] obs and Streamlabs desktop control support (not using bots internal controls)
- [ ] Create dashboard to control plugins and view logs easily (potentially provide more advanced uis for plugins in the future?)
- [ ] Handle plugin updates
- [ ] Use Nuitka to bundle binaries instead of needing to install python (https://pypi.org/project/Nuitka/) (?)
