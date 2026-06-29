# Agent Instructions

## Do not hard-code paths in `src/`

Any filesystem path that refers to a user's home directory, an OS-specific location, or a WINE prefix must be configurable — never hard-coded.

Prohibited examples:
- `C:\users\brosnan\...`
- `~/.wine/drive_c/...`
- `/home/$USER/.wine/...`

Use `os.path.expanduser` with a configurable default or accept the path via function parameter or settings dict.
