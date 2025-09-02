from __future__ import annotations

import asyncio
from threading import Event, Thread
from typing import Any

from azure.core.credentials import AccessToken, TokenCredential
from azure.core.credentials_async import AsyncTokenCredential


class AsyncToSyncCredentialAdapter(TokenCredential):
    def __init__(self, async_cred: AsyncTokenCredential) -> None:
        self._async_cred = async_cred
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = Event()
        self._thread = Thread(target=self._run_loop, name="azure-cred-adapter", daemon=True)
        self._thread.start()
        self._ready.wait()

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._ready.set()
        loop.run_forever()

    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        loop = self._loop
        if loop is None:
            raise RuntimeError("credential loop not ready")
        fut = asyncio.run_coroutine_threadsafe(self._async_cred.get_token(*scopes, **kwargs), loop)
        return fut.result()

    def close(self) -> None:
        loop = self._loop
        if loop is None:
            return
        aclose = getattr(self._async_cred, "aclose", None)
        if callable(aclose):
            fut = asyncio.run_coroutine_threadsafe(aclose(), loop)
            fut.result()
        loop.call_soon_threadsafe(loop.stop)
        self._thread.join(timeout=2)
        self._loop = None


def ensure_sync_credential(cred: TokenCredential | AsyncTokenCredential) -> TokenCredential:
    if isinstance(cred, AsyncTokenCredential):
        return AsyncToSyncCredentialAdapter(cred)
    return cred
