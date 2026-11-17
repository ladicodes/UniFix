"""An httpx transport for stellar-sdk's async servers (keeps one HTTP stack in the app)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import httpx
from stellar_sdk.client.base_async_client import BaseAsyncClient
from stellar_sdk.client.response import Response
from stellar_sdk.exceptions import ConnectionError as StellarConnectionError


class HttpxAsyncClient(BaseAsyncClient):
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get(
        self, url: str, params: dict[str, str] | None = None, max_content_size: int | None = None
    ) -> Response:
        try:
            response = await self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise StellarConnectionError(exc) from exc
        return Response(response.status_code, response.text, dict(response.headers), str(response.url))

    async def post(
        self, url: str, data: dict[str, str] | None = None, json_data: dict[str, Any] | None = None
    ) -> Response:
        try:
            response = await self._client.post(url, data=data, json=json_data)
        except httpx.HTTPError as exc:
            raise StellarConnectionError(exc) from exc
        return Response(response.status_code, response.text, dict(response.headers), str(response.url))

    def stream(  # pragma: no cover - streaming is not used
        self, url: str, params: dict[str, str] | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        raise NotImplementedError("Event streaming is not used; the reconciler polls getEvents.")

    async def close(self) -> None:
        await self._client.aclose()
