"""Row text for the VS Code recents menu.

Each recent entry is shown as a name plus a detail: a folder's own name over the path it lives in,
or a file's name beside the folder it sits in. Remote entries describe the connection instead of a
local path. Kept free of Qt so it can be tested on its own.
"""

import ntpath
import urllib.parse

from core.widgets.services.vscode.history import RecentWorkspace


def describe_remote_authority(authority: str | None) -> str:
    """Turn a VS Code remote authority such as ``wsl+Ubuntu`` into a short description."""
    if not authority:
        return "Remote Connection"
    auth_lower = authority.lower()
    if auth_lower.startswith("wsl+"):
        distro = authority[4:]
        return f"WSL ({distro})" if distro else "WSL Connection"
    if auth_lower.startswith("ssh-remote+"):
        host = authority[11:]
        return f"SSH ({host})" if host else "SSH Connection"
    if auth_lower.startswith("dev-container+"):
        return "Dev Container"
    return f"Remote: {authority}"


def split_local_path(path: str) -> tuple[str, str]:
    """Split a Windows path into its last component and the path of its parent.

    Separators come back as backslashes and a trailing separator is ignored. A drive root has no
    last component, so it becomes its own name (``D:\\``) with an empty parent.
    """
    normalized = path.replace("/", "\\")
    drive, rest = ntpath.splitdrive(normalized)
    rest = rest.rstrip("\\")
    if not rest:
        return (f"{drive}\\" if drive else normalized), ""
    parent, name = ntpath.split(drive + rest)
    return name, parent


def _remote_parts(uri: str) -> tuple[str, list[str]]:
    """Return a remote URI's authority and its path components (empty for the root)."""
    parsed = urllib.parse.urlparse(uri)
    authority = urllib.parse.unquote(parsed.netloc)
    remote_path = urllib.parse.unquote(parsed.path).replace("\\", "/").strip("/")
    return authority, remote_path.split("/") if remote_path else []


def workspace_row_text(workspace: RecentWorkspace) -> tuple[str, str]:
    """Return the ``(name, detail)`` pair shown for a recent workspace.

    Folders: the folder name, then its parent path (local) or the connection (remote).
    Files: the file name, then the name of the folder holding it, plus the connection when remote.
    """
    is_file = workspace["type"] == "file"
    path = workspace["path"]

    if workspace["is_remote"]:
        uri_authority, parts = _remote_parts(path)
        connection = describe_remote_authority(workspace.get("remote_authority") or uri_authority)
        name = parts[-1] if parts else "/"
        if not is_file:
            return name, connection
        folder = parts[-2] if len(parts) > 1 else "/"
        return name, f"{folder} · {connection}"

    name, parent = split_local_path(path)
    if not is_file:
        return name, parent
    return name, split_local_path(parent)[0] if parent else ""
