"""Credential storage via the OS keychain (keyring). Env vars HEARTHFORGE_KEY_<ID> also work.

If no secure backend exists, saving is refused rather than falling back to plaintext files.
"""
from __future__ import annotations

import os
import re

SERVICE = "hearthforge"


class SecretError(Exception):
    pass


def env_name(provider_id: str) -> str:
    return "HEARTHFORGE_KEY_" + re.sub(r"[^A-Za-z0-9]", "_", provider_id).upper()


class SecretStore:
    def __init__(self, backend=None):
        """backend: object with get_password/set_password/delete_password (keyring API)."""
        self._backend = backend
        self._checked = backend is not None
        self._session: dict[str, str] = {}

    def _kr(self):
        if self._backend is None and not self._checked:
            self._checked = True
            try:
                import keyring
                from keyring.backends import fail

                kr = keyring.get_keyring()
                if not isinstance(kr, fail.Keyring) and kr.__class__.__module__ != "keyring.backends.null":
                    self._backend = keyring
            except Exception:
                self._backend = None
        return self._backend

    @property
    def secure_backend_available(self) -> bool:
        return self._kr() is not None

    def get(self, provider_id: str) -> str | None:
        v = os.environ.get(env_name(provider_id))
        if v:
            return v
        if provider_id in self._session:
            return self._session[provider_id]
        kr = self._kr()
        if kr:
            try:
                return kr.get_password(SERVICE, provider_id)
            except Exception:
                return None
        return None

    def has(self, provider_id: str) -> bool:
        return bool(self.get(provider_id))

    def set(self, provider_id: str, value: str, allow_session: bool = False) -> str:
        """Returns where the key was kept: 'keychain' or 'session' (memory only, lost on restart)."""
        kr = self._kr()
        if kr:
            kr.set_password(SERVICE, provider_id, value)
            self._session.pop(provider_id, None)
            return "keychain"
        if allow_session:
            self._session[provider_id] = value
            return "session"
        raise SecretError(
            f"No OS credential store available. Set the environment variable {env_name(provider_id)} instead."
        )

    def delete(self, provider_id: str) -> None:
        self._session.pop(provider_id, None)
        kr = self._kr()
        if kr:
            try:
                kr.delete_password(SERVICE, provider_id)
            except Exception:
                pass

    def all_values(self, provider_ids: list[str]) -> list[str]:
        return [v for v in (self.get(p) for p in provider_ids) if v]
