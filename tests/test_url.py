import builtins
import pathlib
from typing import Any, cast

import pytest


class _DummyCoreSchemaHandler:
    def __call__(self, value: Any, /) -> Any:
        return value


from type_url import (
    URL,
    BaseURL,
    base_url_config,
    parse_path,
    url_config,
)


class TestURLConfig:
    def test_parse_path_defaults_and_normalizes_strings(self):
        assert parse_path(None) == pathlib.PurePosixPath("/")
        assert parse_path("users") == pathlib.PurePosixPath("/users")
        assert parse_path("/users") == pathlib.PurePosixPath("/users")
        path = pathlib.PurePosixPath("/users")
        assert parse_path(path) is path

    def test_makes_absolute_and_relative_urls(self):
        config = url_config(scheme="https", host="example.com", port=443, path="/api")

        assert config.make_url("https://other.example/users") == URL(
            scheme="https",
            host="other.example",
            port=None,
            path=pathlib.PurePosixPath("/users"),
            query=None,
            fragment=None,
        )
        assert str(config.make_url("/users?active=true")) == "https://example.com:443/users?active=true"
        assert str(config.make_url("")) == "https://example.com:443/api"

    def test_requires_missing_scheme_or_host(self):
        with pytest.raises(ValueError, match="Scheme must be provided"):
            url_config(host="example.com").make_url("users")

        with pytest.raises(ValueError, match="Scheme must be provided"):
            url_config(host="example.com").make_url("/users")

        with pytest.raises(ValueError, match="Host must be provided"):
            url_config(scheme="https").make_url("/users")

    def test_raises_when_pydantic_core_is_missing(self, monkeypatch: pytest.MonkeyPatch):
        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "pydantic_core":
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(RuntimeError, match="pydantic_core is required"):
            url_config(scheme="https", host="example.com", path="/api").__get_pydantic_core_schema__(
                URL,
                cast(Any, _DummyCoreSchemaHandler()),
            )

    def test_uses_explicit_port_and_host_from_url(self):
        config = url_config(scheme="https", host="example.com", port=443, path="/api")

        assert str(config.make_url("//other.example:8443/users")) == "https://other.example:8443/users"


class TestURL:
    def test_from_url_parses_components_and_round_trips(self):
        url = URL.from_url("https://example.com:8443/users?active=true#results")

        assert url == URL(
            scheme="https",
            host="example.com",
            port=8443,
            path=pathlib.PurePosixPath("/users"),
            query="active=true",
            fragment="results",
        )
        assert url.netloc == "example.com:8443"
        assert str(url) == "https://example.com:8443/users?active=true#results"

    @pytest.mark.parametrize(
        ("value", "message"),
        [
            ("example.com/path", "URL must have a scheme."),
            ("https:///path", "URL must have a host."),
        ],
    )
    def test_from_url_rejects_incomplete_urls(self, value: str, message: str):
        with pytest.raises(ValueError, match=message):
            URL.from_url(value)

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            # URL.joinpath follows PurePosixPath, so an absolute path replaces the existing path.
            ("/api/v1", "https://example.com/api/v1"),
            # A relative path is appended to the existing URL path.
            ("api/v1", "https://example.com/api/v2/api/v1"),
            # URL.__str__ normalizes parent traversal against the absolute URL path.
            ("../flaf/demo", "https://example.com/api/flaf/demo"),
            # Current-directory components are normalized away by PurePosixPath.
            ("./flaf", "https://example.com/api/v2/flaf"),
            # URL.__str__ normalizes traversal to the parent path.
            ("../", "https://example.com/api"),
        ],
    )
    def test_joinpath(self, path: str, expected: str):
        url = URL.from_url("https://example.com/api/v2/")

        assert str(url.joinpath(path)) == expected

    def test_joinpath_and_resolve(self):
        url = URL.from_url("https://example.com/api")

        joined = url.joinpath("v1", pathlib.PurePosixPath("users"))

        assert joined.path == pathlib.PurePosixPath("/api/v1/users")
        assert joined.resolve("42") == "https://example.com/api/v1/users/42"
        assert url.path == pathlib.PurePosixPath("/api")


class TestBaseURLConfig:
    def test_makes_relative_urls(self):
        config = base_url_config(scheme="https", host="example.com", path="/api")

        assert config.make_url("/users").path == pathlib.PurePosixPath("/users")
        assert str(config.make_url("/users")) == "https://example.com/users"
        assert str(config.make_url("")) == "https://example.com/api"

    def test_requires_missing_scheme_or_host(self):
        with pytest.raises(ValueError, match="Scheme must be provided"):
            base_url_config(host="example.com").make_url("users")

        with pytest.raises(ValueError, match="Scheme must be provided"):
            base_url_config(host="example.com").make_url("/users")

        with pytest.raises(ValueError, match="Host must be provided"):
            base_url_config(scheme="https").make_url("/users")

    def test_uses_explicit_scheme_for_absolute_url(self):
        config = base_url_config(host="example.com", path="/api")

        assert str(config.make_url("https://other.example/users")) == "https://other.example/users"

    def test_raises_when_pydantic_core_is_missing(self, monkeypatch: pytest.MonkeyPatch):
        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "pydantic_core":
                raise ImportError("missing")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(RuntimeError, match="pydantic_core is required"):
            base_url_config(scheme="https", host="example.com", path="/api").__get_pydantic_core_schema__(
                BaseURL,
                cast(Any, _DummyCoreSchemaHandler()),
            )

    def test_uses_explicit_port_and_host_from_url(self):
        config = base_url_config(scheme="https", host="example.com", port=443, path="/api")

        assert str(config.make_url("//other.example:8443/users")) == "https://other.example:8443/users"


class TestBaseURL:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            # BaseURL treats every input as a sub-path, including an absolute-looking path.
            ("/api/v1", "https://example.com/api/v2/api/v1"),
            # A relative path is appended to the BaseURL path.
            ("api/v1", "https://example.com/api/v2/api/v1"),
            # BaseURL normalizes parent traversal before joining it to the base path.
            ("../flaf/demo", "https://example.com/api/v2/flaf/demo"),
            # Current-directory components are normalized away.
            ("./flaf", "https://example.com/api/v2/flaf"),
            # Traversal is clamped at the sub-path root before joining the base path.
            ("../", "https://example.com/api/v2"),
        ],
    )
    def test_joinpath(self, path: str, expected: str):
        url = BaseURL.from_url("https://example.com/api/v2/")

        assert str(url.joinpath(path)) == expected

    def test_from_url_and_sub_paths(self):
        url = BaseURL.from_url("https://example.com/api?version=1#top")

        assert url.path == pathlib.PurePosixPath("/api")
        assert url.query == "version=1"
        assert str(url.joinpath("users", "42")) == "https://example.com/api/users/42?version=1#top"

        sub_base = url.sub_base("users")
        assert sub_base.base_path == pathlib.PurePosixPath("/api/users")
        assert sub_base.sub_path == pathlib.PurePosixPath()
        assert sub_base.resolve("42") == "https://example.com/api/users/42?version=1#top"

    @pytest.mark.parametrize(
        ("url", "message"),
        [
            ("example.com/path", "BaseURL must have a scheme"),
            ("https:///path", "BaseURL must have a host"),
        ],
    )
    def test_from_url_rejects_incomplete_urls(self, url: str, message: str):
        with pytest.raises(ValueError, match=message):
            BaseURL.from_url(url)

    def test_netloc_and_str_use_parent_host_when_port_is_missing(self):
        url = BaseURL.from_url("https://example.com/api")

        assert url.netloc == "example.com"
        assert str(url) == "https://example.com/api"
