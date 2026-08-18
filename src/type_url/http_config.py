from __future__ import annotations

import pathlib
import ssl as _ssl
from collections.abc import Callable
from datetime import timedelta
from typing import Literal, NotRequired, TypedDict

import httpx
import pydantic

# region SSL


def create_insecure_ssl_context() -> _ssl.SSLContext:
    ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = _ssl.CERT_NONE
    return ctx


class SSLConfig(pydantic.BaseModel):
    cafile: pathlib.Path | None = None
    capath: pathlib.Path | None = None
    cadata: str | bytes | None = None


def create_ssl_context(ssl_config: SSLConfig | bool | None) -> _ssl.SSLContext:
    match ssl_config:
        case None:
            return _ssl.create_default_context()
        case SSLConfig():
            return _ssl.create_default_context(
                cafile=ssl_config.cafile,
                capath=ssl_config.capath,
                cadata=ssl_config.cadata,
            )
        case bool():
            if ssl_config is False:
                return create_insecure_ssl_context()
            return _ssl.create_default_context()


# endregion

# region Timeout


class TimeoutDict(TypedDict):
    timeout: NotRequired[float | None]
    read: NotRequired[float | None]
    write: NotRequired[float | None]
    connect: NotRequired[float | None]


class TimeoutConfig(pydantic.BaseModel):
    timeout: timedelta | Literal[False] | None = None
    read_timeout: timedelta | Literal[False] | None = None
    write_timeout: timedelta | Literal[False] | None = None
    connect_timeout: timedelta | Literal[False] | None = None

    def create_timeout(self) -> httpx.Timeout | None:
        if (
            self.timeout is None
            and self.read_timeout is None
            and self.write_timeout is None
            and self.connect_timeout is None
        ):
            return None

        timeout_dct: TimeoutDict = {}
        if self.timeout is not None:
            timeout_dct["timeout"] = None if self.timeout is False else self.timeout.total_seconds()
        if self.read_timeout is not None:
            timeout_dct["read"] = None if self.read_timeout is False else self.read_timeout.total_seconds()
        if self.write_timeout is not None:
            timeout_dct["write"] = None if self.write_timeout is False else self.write_timeout.total_seconds()
        if self.connect_timeout is not None:
            timeout_dct["connect"] = None if self.connect_timeout is False else self.connect_timeout.total_seconds()
        return httpx.Timeout(**timeout_dct)


def create_timeout(value: timedelta | Literal[False] | TimeoutConfig | None) -> httpx.Timeout | None:
    match value:
        case None:
            return None
        case TimeoutConfig():
            return value.create_timeout()
        case timedelta():
            return httpx.Timeout(timeout=value.total_seconds())
        case False:
            return httpx.Timeout(timeout=None)


# endregion

# region Limits


class LimitConfig(pydantic.BaseModel):
    max_connections: int | None = None
    max_keepalive_connections: int | None = None


def create_limits(value: LimitConfig | None) -> httpx.Limits | None:
    if value is None:
        return None
    return httpx.Limits(
        max_connections=value.max_connections,
        max_keepalive_connections=value.max_keepalive_connections,
    )


# endregion

# region Transport


class TransportDict(TypedDict):
    verify: _ssl.SSLContext
    proxy: NotRequired[str]
    limits: NotRequired[httpx.Limits]


def create_transport_dct(http_config: HTTPConfig | None) -> TransportDict:
    if http_config is None:
        http_config = HTTPConfig()

    transport_dct: TransportDict = {
        "verify": create_ssl_context(http_config.ssl),
    }

    if (proxy := http_config.proxy) is not None:
        transport_dct["proxy"] = proxy

    if (limits := create_limits(http_config.limits)) is not None:
        transport_dct["limits"] = limits

    return transport_dct


def create_async_transport(
    http_config: HTTPConfig | None = None,
    middleware: Callable[[httpx.AsyncBaseTransport], httpx.AsyncBaseTransport] | None = None,
) -> httpx.AsyncBaseTransport:

    transport = httpx.AsyncHTTPTransport(**create_transport_dct(http_config))
    if middleware is not None:
        transport = middleware(transport)
    return transport


def create_sync_transport(
    http_config: HTTPConfig | None = None,
    middleware: Callable[[httpx.BaseTransport], httpx.BaseTransport] | None = None,
) -> httpx.BaseTransport:

    transport = httpx.HTTPTransport(**create_transport_dct(http_config))
    if middleware is not None:
        transport = middleware(transport)
    return transport


# endregion

# region Client


class ClientDict(TypedDict):
    timeout: NotRequired[httpx.Timeout]


def _add_client_params(client_dct: ClientDict, config: HTTPConfig) -> None:
    if (timeout := create_timeout(config.timeout)) is not None:
        client_dct["timeout"] = timeout


class AsyncClientDict(ClientDict):
    transport: httpx.AsyncBaseTransport


def create_async_client(
    http_config: HTTPConfig | None = None,
    middleware: Callable[[httpx.AsyncBaseTransport], httpx.AsyncBaseTransport] | None = None,
    auth: Callable[[httpx.AsyncClient], httpx.Auth] | httpx.Auth | None = None,
) -> httpx.AsyncClient:

    if http_config is None:
        http_config = HTTPConfig()

    client_dct: AsyncClientDict = {
        "transport": create_async_transport(http_config, middleware=middleware),
    }

    _add_client_params(client_dct, http_config)

    client = httpx.AsyncClient(**client_dct)
    if isinstance(auth, httpx.Auth):
        client.auth = auth
    elif auth is not None:
        client.auth = auth(client)
    return client


class SyncClientDict(ClientDict):
    transport: httpx.BaseTransport


def create_sync_client(
    http_config: HTTPConfig | None = None,
    middleware: Callable[[httpx.BaseTransport], httpx.BaseTransport] | None = None,
    auth: Callable[[httpx.Client], httpx.Auth] | httpx.Auth | None = None,
) -> httpx.Client:

    if http_config is None:
        http_config = HTTPConfig()

    client_dct: SyncClientDict = {
        "transport": create_sync_transport(http_config, middleware=middleware),
    }

    _add_client_params(client_dct, http_config)

    client = httpx.Client(**client_dct)
    if isinstance(auth, httpx.Auth):
        client.auth = auth
    elif auth is not None:
        client.auth = auth(client)
    return client


# endregion


class HTTPConfig(pydantic.BaseModel):
    proxy: str | None = None
    timeout: timedelta | Literal[False] | TimeoutConfig | None = None
    limits: LimitConfig | None = None
    ssl: bool | SSLConfig | None = None
