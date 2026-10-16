import pydantic
import pytest

from rendercv.renderer.templater.templater import render_full_template
from rendercv.schema.models.cv.custom_connection import CustomConnection
from rendercv.schema.models.rendercv_model import RenderCVModel


def test_url_is_optional_in_model_and_schema():
    connection = CustomConnection(fontawesome_icon="phone", placeholder="Contact")
    assert connection.url is None
    schema = CustomConnection.model_json_schema()
    assert "url" not in schema["required"]
    assert schema["properties"]["url"]["default"] is None


@pytest.mark.parametrize("file_type", ["typst", "markdown"])
def test_omitted_connection_url_renders_like_explicit_null(file_type):
    connection = {"fontawesome_icon": "phone", "placeholder": "Contact"}
    model = RenderCVModel.model_validate(
        {"cv": {"name": "Example", "custom_connections": [connection]}}
    )
    reference = RenderCVModel.model_validate(
        {"cv": {"name": "Example", "custom_connections": [{**connection, "url": None}]}}
    )
    rendered = render_full_template(model, file_type)
    if file_type == "typst":
        assert "Contact" in rendered
    assert rendered == render_full_template(reference, file_type)


def test_invalid_connection_url_is_still_rejected():
    with pytest.raises(pydantic.ValidationError):
        CustomConnection.model_validate(
            {"fontawesome_icon": "phone", "placeholder": "Contact", "url": "bad"}
        )
