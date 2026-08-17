from __future__ import annotations

import dataclasses
import pathlib
import urllib.parse
from typing import TYPE_CHECKING, Any, NamedTuple, Self

if TYPE_CHECKING:
    from pydantic import GetCoreSchemaHandler
    from pydantic_core import CoreSchema
else:
    type GetCoreSchemaHandler = object
    type CoreSchema = object

__version__ = "0.1.3"


def make_url(default: URLConfig, url: str) -> URL:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme == "" and parsed.netloc == "" and not url.startswith("/"):
        if default.scheme is None:
            raise ValueError("Scheme must be provided either in URLConfig or in the URL.")
        parsed = urllib.parse.urlsplit(f"{default.scheme}://{url}")
        parsed = parsed._replace(scheme="")

    scheme = parsed.scheme or default.scheme
    if scheme is None:
        raise ValueError("Scheme must be provided either in URLConfig or in the URL.")

    # Determine the port to use based on the parsed URL scheme and port.
    # If scheme is non-empty, use the parsed_url.port (which may be None).
    # If scheme is empty (relative URL), use parsed_url.port if provided, otherwise use default port.
    match (parsed.scheme, parsed.port):
        case ("", int()):
            # Empty scheme with explicit port: use the parsed port
            port = parsed.port
        case ("", None):
            # Empty scheme with no port: use default port from config
            port = default.port
        case _:
            # Non-empty scheme: use the parsed port (may be None)
            port = parsed.port

    host = parsed.hostname if parsed.hostname is not None else default.host
    if host is None:
        raise ValueError("Host must be provided either in URLConfig or in the URL.")

    path = pathlib.PurePosixPath(parsed.path) if parsed.path != "" else default._path

    return URL(
        scheme=scheme,
        host=host,
        port=port,
        path=path,
        query=parsed.query or None,
        fragment=parsed.fragment or None,
    )


@dataclasses.dataclass
class URLConfig:
    scheme: str | None = None
    host: str | None = None
    port: int | None = None
    path: dataclasses.InitVar[str | pathlib.PurePosixPath | None] = None
    _path: pathlib.PurePosixPath = dataclasses.field(init=False)

    def __post_init__(self, path: str | pathlib.PurePosixPath | None) -> None:
        if path is None:
            self._path = pathlib.PurePosixPath("/")
        elif isinstance(path, str):
            if not path.startswith("/"):
                path = "/" + path
            self._path = pathlib.PurePosixPath(path)
        else:
            self._path = path

    def make_url(self, url: str) -> URL:
        return make_url(self, url)

    def __get_pydantic_core_schema__(
        self,
        _source_type: Any,
        _handler: GetCoreSchemaHandler,
    ) -> CoreSchema:

        try:
            from pydantic_core import core_schema
        except ImportError as e:
            raise RuntimeError(
                "pydantic_core is required for using URLConfig with Pydantic please install type-url[pydantic]"
            ) from e

        str_schema = _handler(str)

        plain_schema = core_schema.no_info_plain_validator_function(
            self.make_url,
        )
        json_schema = core_schema.chain_schema(
            steps=[
                str_schema,
                plain_schema,
            ]
        )
        return core_schema.json_or_python_schema(
            json_schema=json_schema,
            python_schema=core_schema.union_schema(
                choices=[
                    core_schema.is_instance_schema(_source_type),
                    json_schema,
                ]
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                URL.__str__,
                return_schema=str_schema,
                when_used="json-unless-none",
            ),
        )


class URL(NamedTuple):
    scheme: str | None
    host: str | None
    port: int | None
    path: pathlib.PurePosixPath
    query: str | None
    fragment: str | None

    @property
    def netloc(self) -> str:
        """
        Return the network location part of the URL.

        Returns:
            str: The network location part of the URL.
        """
        if self.host is None:
            return ""
        if self.port is None:
            return self.host
        return f"{self.host}:{self.port}"

    @classmethod
    def from_url(cls, url: str) -> Self:
        parsed_url = urllib.parse.urlsplit(url)
        return cls(
            scheme=parsed_url.scheme or None,
            host=parsed_url.hostname or None,
            port=parsed_url.port,
            path=pathlib.PurePosixPath(parsed_url.path) if parsed_url.path else pathlib.PurePosixPath("/"),
            query=parsed_url.query or None,
            fragment=parsed_url.fragment or None,
        )

    def __str__(self) -> str:
        """
        Return the string representation of the URL.

        Returns:
            str: The string representation of the URL.
        """
        return urllib.parse.urlunsplit(
            (
                self.scheme or "",
                self.netloc,
                str(self.path),
                self.query or "",
                self.fragment or "",
            )
        )

    def joinpath(self, *paths: str | pathlib.PurePosixPath) -> Self:
        """
        Join the given paths to the URL's path.

        Args:
            *paths (str | pathlib.PurePosixPath): The paths to join.

        Returns:
            URL: A new URL instance with the joined path.
        """
        _paths = [pathlib.PurePosixPath(p) for p in paths]
        _paths = [p.relative_to("/") if p.is_absolute() else p for p in _paths]

        return self._replace(path=self.path.joinpath(*_paths))
