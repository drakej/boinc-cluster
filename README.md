BOINC Cluster
=============

Flask Application for monitoring and managing a BOINC cluster (multiple hosts).

Also includes python API bindings for the XML RPC_GUI API that the BOINC core client exposes.

The Problem
-----------

- There's currently a lack of easily deployable web applications to manage and monitor multiple BOINC clients (as a cluster of sorts)

The Solution
------------

- A flask application that utilizes the existing python code provided by boinc-indicator. A huge thanks to Rodrigo Silva who wrote that code for Linux in python and saved myself a lot of time of having to reimplement the RPC API in python (BOINC itself uses C/C++) 


The Approach
------------

- `gui_rpc_client.py` is a re-write of `gui_rpc_client.{h,cpp}` in Python. Should provide the GUI_RPC API as faithfully as possible, in a Pythonic way, similar to what PyGTK/PyGI/PyGObject/gir bindings do with Gtk/GLib/etc libs. It starts as direct copy-and-paste of the C++ code as comments, and is progressively translated to Python code. C++ structs and enums are converted to classes, `class RpcClient()` being the port of `struct RPC_CLIENT`.

- `client.py` is a conversion of `boinccmd`, not only from C++ to Python, but also from a command-line utility to an API library. Uses `gui_rpc_client.RpcClient` calls to provide an interface that closely matches the command-line options of `boinccmd`, ported as methods of a `BoincClient` class.

- `boinccluster.py` is the Flask application code which utilizes the BOINC client code in client.py which in turn uses rpc.py

- Since API and App Indicator are distinct, in the future they they can be packaged separately: API as a library package named `python-boinc-gui-rpc` or similar, installed somewhere in `PYTHONPATH`, while the app indicator monitor can be, for example `boinc-monitor` or `boinc-indicator`. Indicator depends on API and recommends `boinc-manager`, and API depends on `boinc-client`.


The Challenges
--------------

TBD

Requirements
------------

- Python (tested in 3.10)
- BOINC Client install accessible via TCP/IP LAN


Using the API library
---------------------

Package and modules names are not set in stone yet. Actually, API is still a non-working stub. But, assuming a `boinc` package in `PYTHONPATH`, it will be something like:

For the client API (emulating the options of `boinccmd`):

	from boinc.client import BoincClient
	bc = BoincClient()
	status = bc.get_cc_status()

For the XML GUI_RPC API:

	from boinc.gui_rpc_client import RpcClient
	rpc = RpcClient()
	rpc.init()
	status = rpc.get_status()

The idea is to make the client API somewhat higher-lever and a bit more straightforward than the GUI_RPC, since it automatically deals with deals with `exchange_version()`, `read_gui_rpc_password()` and `authorize()`, but it also may have fewer features. Maybe in the future we realize having 2 layers is pointless, and merge both in a single module that provides both complete feature set and straightforward usage. Only time (or you) will tell.


Written by
----------

- Rodigo Silva (MestreLion) <linux@rodrigosilva.com>
- Jonathan Drake (drakej)


Licenses and Copyright
----------------------

Copyright (C) 2013 Rodigo Silva (MestreLion) <linux@rodrigosilva.com>.
Copyright (C) 2020 Jonathan Drake (drakej).

License GPLv3+: GNU GPL version 3 or later <http://gnu.org/licenses/gpl.html>.

This is free software: you are free to change and redistribute it.

There is NO WARRANTY, to the extent permitted by law.

  [1]: https://boinc.berkeley.edu/wiki/The_BOINC_Manager
  [2]: http://www.boinc-wiki.info/BOINC_Manager
  [3]: http://askubuntu.com/questions/30742
  [4]: http://www.webupd8.org/2013/02/unity-notification-area-systray.html
  [5]: http://boinc.berkeley.edu/dev/forum_thread.php?id=7582
  [6]: http://askubuntu.com/questions/191806
  [7]: https://bugs.launchpad.net/ubuntu/+source/boinc/+bug/926891
  [8]: http://askubuntu.com/questions/191743
  [9]: http://boinc.berkeley.edu/trac/wiki/GuiRpc
  [10]: http://askubuntu.com/questions/14555
  [11]: http://bugs.python.org/issue14138
  [12]: https://bugzilla.gnome.org/show_bug.cgi?id=622084
  [13]: https://bugzilla.gnome.org/show_bug.cgi?id=695683
  [14]: https://github.com/MestreLion/boinc-indicator/issues
