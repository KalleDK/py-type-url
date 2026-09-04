from typing import Annotated

import pytest

from type_url import URL, BaseURL, base_url_config, url_config

try:
    import pydantic
except ImportError:
    pytest.skip("pydantic is not installed", allow_module_level=True)


class TestPydanticURLConfig:
    def test_url_model_round_trip(self):

        class Model(pydantic.BaseModel):
            url: Annotated[URL, url_config(scheme="https", host="example.com", path="/api")]

        model = Model.model_validate({"url": "/users"})

        assert model.url == URL.from_url("https://example.com/users")
        assert Model.model_validate({"url": model.url}).url == model.url
        assert model.model_dump_json() == '{"url":"https://example.com/users"}'


class TestPydanticBaseURLConfig:
    def test_base_url_model_round_trip(self):

        class Model(pydantic.BaseModel):
            url: Annotated[BaseURL, base_url_config(scheme="https", host="example.com", path="/api")]

        model = Model.model_validate({"url": "/users"})

        assert model.url == BaseURL.from_url("https://example.com/users")
        assert Model.model_validate({"url": model.url}).url == model.url
        assert model.model_dump_json() == '{"url":"https://example.com/users"}'
