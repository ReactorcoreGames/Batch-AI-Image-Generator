"""Credential storage.

Keys are entered in the GUI and saved to `credentials.json` next to the
program. That is the primary, supported path -- the audience for this tool is
not expected to know what an environment variable is, let alone that Windows
only hands them to processes started afterwards.

What the original "env vars only" rule was actually protecting against still
holds, and still does here:

  * NOT config.json -- a config file gets pasted into bug reports and copied
    between machines.
  * NOT the job database -- that travels with an output folder.
  * NOT the repo -- gitignored by name.

Environment variables are still read, and still take priority, so an existing
CI or power-user setup keeps working. They are simply no longer the thing a
first-time user is told to go and configure.

There is no encryption, deliberately: encrypting a local file with a key
stored on the same machine protects nothing. This is the trust level of a
.env file, which is the normal way to hold a personal API key on a desktop.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Field definitions drive the whole settings UI — add a provider here and the
# form picks it up.
FIELDS: list[dict] = [
    {
        "key": "CLOUDFLARE_ACCOUNT_ID",
        "label": "Cloudflare Account ID",
        "provider": "cloudflare",
        "secret": False,
        "help": "Found on the right-hand side of your Cloudflare dashboard "
                "overview page, or in the address bar after /accounts/. Not "
                "secret, but needed to send requests.",
        "url": "https://dash.cloudflare.com/",
    },
    {
        "key": "CLOUDFLARE_API_TOKEN",
        "label": "Cloudflare API Token",
        "provider": "cloudflare",
        "secret": True,
        "help": "Create one at Cloudflare > My Profile > API Tokens using "
                "the 'Read all resources' template - verified sufficient for "
                "both the free and paid models, and harmless if it leaks, "
                "because this program only ever reads. Treat it like a "
                "password anyway.",
        "url": "https://dash.cloudflare.com/profile/api-tokens",
    },
    {
        "key": "POLLINATIONS_API_KEY",
        "label": "Pollinations API Key (optional)",
        "provider": "pollinations",
        "secret": True,
        "help": "Only needed for the 'Pollinations - with API key' mode. "
                "Without a key Pollinations allows just one queued request at "
                "a time per IP address, which makes batches very slow.",
        "url": "https://enter.pollinations.ai",
    },
]

FIELDS_BY_KEY = {f["key"]: f for f in FIELDS}


def credentials_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "credentials.json"
    return Path(__file__).resolve().parent.parent / "credentials.json"


def load_credentials() -> dict[str, str]:
    """Read the saved credentials file. Missing or malformed reads as empty."""
    try:
        data = json.loads(credentials_path().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {k: str(v) for k, v in data.items()
                if k in FIELDS_BY_KEY and v}
    except Exception:
        return {}


def save_credentials(values: dict[str, str]) -> tuple[bool, str]:
    """Write the credentials file, dropping blanks. (ok, message)."""
    clean = {k: v.strip() for k, v in values.items()
             if k in FIELDS_BY_KEY and v and v.strip()}
    path = credentials_path()
    try:
        if clean:
            path.write_text(json.dumps(clean, indent=2), encoding="utf-8")
            _restrict_permissions(path)
        elif path.exists():
            path.unlink()
        return True, f"Saved to {path.name}"
    except Exception as e:
        return False, f"Could not save: {type(e).__name__}: {e}"


def _restrict_permissions(path: Path) -> None:
    """Limit the file to the current user on Windows.

    Best-effort: the file sits in the user's own folder already, so this is
    defence in depth rather than the main protection. Never fatal.
    """
    if sys.platform != "win32":
        try:
            path.chmod(0o600)
        except Exception:
            pass
        return
    try:
        user = os.environ.get("USERNAME", "")
        if not user:
            return
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass


def apply_to_environment() -> dict[str, str]:
    """Publish saved credentials into os.environ for the provider layer.

    Environment variables set outside the program take priority: someone who
    already has CLOUDFLARE_API_TOKEN exported keeps that behaviour, and this
    file only fills the gaps. Returns the map of what was applied.
    """
    applied: dict[str, str] = {}
    for key, value in load_credentials().items():
        if not os.environ.get(key, "").strip():
            os.environ[key] = value
            applied[key] = value
    return applied


def effective_value(key: str) -> tuple[str, str]:
    """Return (value, source) for a credential.

    source is 'environment', 'saved', or '' when it is not set anywhere.
    """
    saved = load_credentials()
    env = os.environ.get(key, "").strip()
    if env and env != saved.get(key):
        return env, "environment"
    if saved.get(key):
        return saved[key], "saved"
    if env:
        return env, "environment"
    return "", ""


def user_level_env(key: str) -> str:
    """Read a Windows *user* environment variable directly.

    A variable created with setx after this process started is invisible to
    os.environ, which otherwise looks identical to 'never set'.
    """
    if sys.platform != "win32":
        return ""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"[Environment]::GetEnvironmentVariable('{key}','User')"],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.stdout.strip()
    except Exception:
        return ""
