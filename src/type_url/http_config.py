from __future__ import annotations

import contextlib
import dataclasses
import json
import pathlib
import ssl as _ssl
from collections.abc import Callable, Generator
from datetime import datetime, timedelta
from typing import Any, Literal, NotRequired, TypedDict
from zoneinfo import ZoneInfo

import httpx
import pydantic

TZ: ZoneInfo | None = None


def now() -> datetime:
    return datetime.now(TZ)


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

    @classmethod
    def create(
        cls,
        insecure: bool | None = None,
        cafile: pathlib.Path | None = None,
        capath: pathlib.Path | None = None,
        cadata: str | bytes | None = None,
    ) -> SSLConfig | bool | None:
        if insecure is True:
            return False

        if cafile is None and capath is None and cadata is None:
            if insecure is None:
                return None
            return True

        return cls(cafile=cafile, capath=capath, cadata=cadata)


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

# region Logger


@dataclasses.dataclass
class FileSession:
    log_dir: pathlib.Path
    prefix: str
    suffix: str
    idx: int

    def _write_req_headers(self, request: httpx.Request) -> None:
        data = {
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
        }
        self.log_dir.joinpath(f"{self.prefix}_{self.idx:04d}_REQ_HEADERS.json").write_text(json.dumps(data, indent=2))

    def _write_req_body(self, data: bytes) -> None:
        if not data:
            return
        self.log_dir.joinpath(f"{self.prefix}_{self.idx:04d}_REQ_BODY{self.suffix}").write_bytes(data)

    def _write_res_headers(self, response: httpx.Response) -> None:
        data = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
        }
        self.log_dir.joinpath(f"{self.prefix}_{self.idx:04d}_RES_HEADERS.json").write_text(json.dumps(data, indent=2))

    def _write_res_body(self, data: bytes) -> None:
        if not data:
            return
        self.log_dir.joinpath(f"{self.prefix}_{self.idx:04d}_RES_BODY{self.suffix}").write_bytes(data)

    async def awrite_request(self, request: httpx.Request) -> None:
        self._write_req_headers(request)
        self._write_req_body(await request.aread())

    async def awrite_response(self, response: httpx.Response) -> None:
        self._write_res_headers(response)
        self._write_res_body(await response.aread())

    def write_request(self, request: httpx.Request) -> None:
        self._write_req_headers(request)
        self._write_req_body(request.read())

    def write_response(self, response: httpx.Response) -> None:
        self._write_res_headers(response)
        self._write_res_body(response.read())


class FileLogger:
    def __init__(self, log_dir: pathlib.Path, suffix: str = ".txt", create_dir: bool = True) -> None:
        if not log_dir.is_dir():
            if log_dir.exists():
                raise RuntimeError("log_dir is not a directory")
            if not create_dir:
                raise RuntimeError("log_dir does not exists")
            log_dir.mkdir(parents=True)

        self.log_dir = log_dir
        self.prefix = now().strftime("%Y%m%d_%H%M%S")
        self.suffix = suffix
        self._idx = 0

    def get_idx(self) -> int:
        idx = self._idx
        self._idx += 1
        return idx

    @contextlib.contextmanager
    def session(self) -> Generator[FileSession, Any]:
        yield FileSession(self.log_dir, self.prefix, self.suffix, self.get_idx())


class AsyncTransportLogger(httpx.AsyncBaseTransport):
    def __init__(self, transport: httpx.AsyncBaseTransport, log_dir: pathlib.Path, suffix: str = ".txt") -> None:
        self._logger = FileLogger(log_dir, suffix=suffix)
        self.transport = transport

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        with self._logger.session() as session:
            await session.awrite_request(request)
            response = await self.transport.handle_async_request(request)
            await session.awrite_response(response)
            return response


class SyncTransportLogger(httpx.BaseTransport):
    def __init__(self, transport: httpx.BaseTransport, log_dir: pathlib.Path, suffix: str = ".txt") -> None:
        self._logger = FileLogger(log_dir, suffix=suffix)
        self.transport = transport

    def handle_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        with self._logger.session() as session:
            session.write_request(request)
            response = self.transport.handle_request(request)
            session.write_response(response)
            return response


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
    if http_config is not None and http_config.log_path is not None:
        transport = AsyncTransportLogger(transport, http_config.log_path)
    if middleware is not None:
        transport = middleware(transport)
    return transport


def create_sync_transport(
    http_config: HTTPConfig | None = None,
    middleware: Callable[[httpx.BaseTransport], httpx.BaseTransport] | None = None,
) -> httpx.BaseTransport:

    transport = httpx.HTTPTransport(**create_transport_dct(http_config))
    if http_config is not None and http_config.log_path is not None:
        transport = SyncTransportLogger(transport, http_config.log_path)
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
    log_path: pathlib.Path | None = None
