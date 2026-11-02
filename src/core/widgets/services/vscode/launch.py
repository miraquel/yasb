"""Starting VS Code from the recents menu.

YASB is often started elevated (a scheduled task with highest privileges), and anything it starts
with Popen inherits that, so VS Code would open as Administrator. When elevated, the launch is
handed to the desktop shell (Explorer), which starts VS Code with the user's normal token. When not
elevated, or if the shell route fails, VS Code is started the way it always was.
"""

import logging
import ntpath
import os
import shutil
import subprocess
import traceback
from collections.abc import Callable

from core.utils.win32.bindings.ole32 import CoInitialize, CoUninitialize, create_dispatch
from core.utils.win32.bindings.shell32 import IsUserAnAdmin
from core.utils.win32.constants import SW_HIDE, SW_SHOWNORMAL, SWC_DESKTOP, SWFO_NEEDDISPATCH
from core.widgets.services.vscode.history import RecentWorkspace


def build_launch_args(workspace: RecentWorkspace, new_window: bool) -> list[str]:
    """Return the VS Code command-line arguments that open ``workspace``."""
    args = ["--new-window"] if new_window else []
    path = workspace["path"]
    if workspace["is_remote"]:
        args.extend(["--folder-uri" if workspace["type"] == "folder" else "--file-uri", path])
    else:
        args.append(path)
    return args


def resolve_launch_target(
    cli_command: str,
    which: Callable[[str], str | None] = shutil.which,
    isfile: Callable[[str], bool] = os.path.isfile,
) -> tuple[str, int]:
    """Return the file the shell should start for ``cli_command`` and the window show state.

    VS Code's ``bin\\code.cmd`` only runs ``Code.exe`` one folder up, so that exe is started
    directly and no console window flashes. Any other script runs hidden, an exe runs shown, and a
    command that does not resolve is left for the shell to find.
    """
    resolved = which(cli_command)
    if not resolved:
        return cli_command, SW_HIDE

    bin_dir, script = ntpath.split(resolved)
    if script.lower() == "code.cmd" and ntpath.basename(bin_dir).lower() == "bin":
        exe = ntpath.join(ntpath.dirname(bin_dir), "Code.exe")
        if isfile(exe):
            return exe, SW_SHOWNORMAL

    if resolved.lower().endswith(".exe"):
        return resolved, SW_SHOWNORMAL
    return resolved, SW_HIDE


def _desktop_shell_execute(file: str, parameters: str, directory: str, show: int) -> None:
    shell_windows = create_dispatch("Shell.Application").Windows()
    desktop = shell_windows.FindWindowSW(0, 0, SWC_DESKTOP, 0, SWFO_NEEDDISPATCH)
    if desktop is None:
        raise OSError("the desktop shell window was not found")
    desktop.Document.Application.ShellExecute(file, parameters, directory, "open", show)


def shell_execute_unelevated(file: str, parameters: str, directory: str, show: int) -> None:
    """Ask the desktop's Explorer to ShellExecute ``file``, so it starts with Explorer's token.

    Runs on whatever thread calls it, so COM is initialised here and the COM objects are released
    (when the inner call returns) before it is uninitialised again.
    """
    hr = CoInitialize()
    try:
        _desktop_shell_execute(file, parameters, directory, show)
    except Exception as e:
        # A failed call's frames still hold its COM objects; drop them while COM is still up.
        traceback.clear_frames(e.__traceback__)
        raise
    finally:
        if hr >= 0:
            CoUninitialize()


def _popen_launch(cli_command: str, args: list[str]) -> None:
    try:
        subprocess.Popen(
            [cli_command, *args],
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logging.error("Failed to open VS Code with %s: %s", args, e)


def launch_vscode(workspace: RecentWorkspace, cli_command: str, new_window: bool) -> None:
    """Open ``workspace`` in VS Code, un-elevated when this process is elevated."""
    args = build_launch_args(workspace, new_window)
    if IsUserAnAdmin():
        try:
            file, show = resolve_launch_target(cli_command)
            shell_execute_unelevated(file, subprocess.list2cmdline(args), os.path.expanduser("~"), show)
            return
        except Exception as e:
            logging.warning("VS Code: un-elevated launch through the desktop shell failed, using Popen: %s", e)
    else:
        logging.debug("VS Code: process is not elevated, launching with Popen")
    _popen_launch(cli_command, args)
