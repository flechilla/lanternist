"""API keys for remote models: looked up, stored, and kept out of anything we write down.

Lookup order: the environment (OPENROUTER_API_KEY, FAL_KEY), then the OS keychain, then a
0600 file for machines with no keychain. Keys are never stored in the database, and `redact`
scrubs them from error text before it is saved or shown.

    LANTERNIST_KEYRING=0        skip the keychain (tests, headless boxes)
    LANTERNIST_SECRETS_FILE     where the fallback file lives
"""

import logging
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SERVICE = "lanternist"
PROVIDERS = {"openrouter": "OPENROUTER_API_KEY", "fal": "FAL_KEY"}
LABELS = {"openrouter": "OpenRouter", "fal": "fal.ai"}


@dataclass
class Key:
    provider: str
    value: str | None
    source: str | None      # env | keychain | file | fake | None

    @property
    def last4(self) -> str | None:
        return self.value[-4:] if self.value else None


def secrets_file() -> Path:
    return Path(os.path.expanduser(os.environ.get("LANTERNIST_SECRETS_FILE",
                                                  "~/.config/lanternist/secrets.toml")))


def _check(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider '{provider}' (known: {', '.join(PROVIDERS)})")


def _keyring():
    """The OS keychain, or None when it's switched off or there is no usable backend."""
    if os.environ.get("LANTERNIST_KEYRING", "1") == "0":
        return None
    try:
        import keyring

        backend = keyring.get_keyring()
        return keyring if getattr(backend, "priority", 0) >= 1 else None
    except Exception as e:  # noqa: BLE001 - a broken keychain must not break the app
        log.debug("keychain unavailable: %s", e)
        return None


def _read_file() -> dict[str, str]:
    path = secrets_file()
    if not path.is_file():
        return {}
    return {k: v for k, v in tomllib.loads(path.read_text()).items() if isinstance(v, str)}


def _write_file(values: dict[str, str]) -> None:
    path = secrets_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f'{k} = "{v}"\n' for k, v in sorted(values.items()))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(body)
    os.chmod(path, 0o600)


def get_key(provider: str, fake: bool = False) -> Key:
    _check(provider)
    if value := os.environ.get(PROVIDERS[provider], "").strip():
        return Key(provider, value, "env")
    kr = _keyring()
    if kr:
        try:
            if value := kr.get_password(SERVICE, provider):
                return Key(provider, value, "keychain")
        except Exception as e:  # noqa: BLE001
            log.warning("couldn't read the keychain: %s", e)
    if value := _read_file().get(provider):
        return Key(provider, value, "file")
    if fake:
        return Key(provider, f"fake-{provider}-key", "fake")
    return Key(provider, None, None)


def set_key(provider: str, value: str) -> str:
    """Store a key in the keychain, or the 0600 file when there is none; returns where it went."""
    _check(provider)
    value = value.strip()
    if not value or re.search(r"\s", value):
        raise ValueError("that doesn't look like an API key")
    kr = _keyring()
    if kr:
        try:
            kr.set_password(SERVICE, provider, value)
            _clear_file(provider)
            return "keychain"
        except Exception as e:  # noqa: BLE001
            log.warning("couldn't write the keychain, using %s: %s", secrets_file(), e)
    values = _read_file()
    values[provider] = value
    _write_file(values)
    return "file"


def _clear_file(provider: str) -> None:
    values = _read_file()
    if values.pop(provider, None) is not None:
        _write_file(values)


def clear_key(provider: str) -> None:
    """Remove a stored key. A key set in the environment stays; that's the shell's to change."""
    _check(provider)
    kr = _keyring()
    if kr:
        try:
            kr.delete_password(SERVICE, provider)
        except Exception as e:  # noqa: BLE001 - not there is fine
            log.debug("no %s key in the keychain: %s", provider, e)
    _clear_file(provider)


def redact(text: str | None) -> str | None:
    """Replace every known key in `text` with a short marker."""
    if not text:
        return text
    for provider in PROVIDERS:
        key = get_key(provider).value
        if key and len(key) >= 8 and key in text:
            text = text.replace(key, f"<{provider} key …{key[-4:]}>")
    return text
