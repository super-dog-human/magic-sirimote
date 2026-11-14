"""Observed webOS cold-boot modes for the integrated app's retained state.

webOS may widen developer-app directories and old files to 0775 or 0777.
The service/native UIDs cannot chmod package-owned (5999:5000) directories.
These modes are compatibility inputs, never proof of ownership or authenticity:
callers must still check owner/group, type, links, stable identity and contents.
New live request/receipt files retain their exact 0600/0640/0660 checks.
Legacy standalone runtimes retain their existing 0775-only boot policy.
"""
import runtime_bundle as bundle


def directory_modes():
    return (0o770, 0o775, 0o777) if bundle.active() else (0o770, 0o775)


def retained_modes(mode, *, legacy_widened=True):
    if bundle.active():
        return (mode, 0o775, 0o777)
    return (mode, 0o775) if legacy_widened else (mode,)
