import json
import pathlib
from unittest.mock import patch

import pydantic
import pytest

from rendercv.exception import RenderCVUserValidationError
from rendercv.schema.json_schema_generator import generate_json_schema
from rendercv.schema.models.cv.cv import Cv
from rendercv.schema.models.validation_context import ValidationContext
from rendercv.schema.rendercv_model_builder import build_rendercv_dictionary_and_model

FIELDS = [
    "name",
    "headline",
    "location",
    "photo",
    "email",
    "phone",
    "website",
    "social_networks",
    "custom_connections",
]


def test_empty_hidden_fields_preserves_legacy_serialization_and_is_not_shared():
    first, second = Cv(name="Example Candidate"), Cv()
    assert first.hidden_fields == []
    assert "hidden_fields" not in first.model_dump()
    first.hidden_fields.append("name")
    assert second.hidden_fields == []
    assert first.name == "Example Candidate"
    assert json.loads(first.model_dump_json())["hidden_fields"] == ["name"]


@pytest.mark.parametrize("field", FIELDS)
def test_every_supported_field_can_be_hidden(field):
    assert Cv(hidden_fields=[field]).hidden_fields == [field]


@pytest.mark.parametrize(
    "hidden",
    [
        None,
        "photo",
        {},
        True,
        1,
        [None],
        [1],
        [True],
        ["unknown"],
        ["sections"],
        ["Photo"],
        [["photo"]],
        [{"photo": True}],
        ("photo",),
    ],
)
def test_invalid_hidden_fields_report_normal_validation_errors(hidden):
    with pytest.raises(pydantic.ValidationError) as error:
        Cv(hidden_fields=hidden)
    assert error.value.errors()[0]["loc"][0] == "hidden_fields"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", []),
        ("headline", {}),
        ("location", 42),
        ("email", "invalid"),
        ("phone", "invalid"),
        ("website", "invalid"),
        ("social_networks", [{"network": "Unknown", "username": "placeholder"}]),
        (
            "custom_connections",
            [{"fontawesome_icon": "link", "placeholder": "Contact", "url": "invalid"}],
        ),
    ],
)
def test_hidden_ordinary_fields_still_validate(field, value):
    with pytest.raises(pydantic.ValidationError):
        Cv.model_validate({"hidden_fields": [field], field: value})


@pytest.mark.parametrize(
    "photo", ["images/missing.png", "https://example.invalid/unreachable.png"]
)
def test_hidden_photo_does_not_check_resource_existence(tmp_path, photo):
    context = {"context": ValidationContext(input_file_path=tmp_path / "cv.yaml")}
    with (
        patch.object(
            pathlib.Path, "exists", side_effect=AssertionError("Unexpected photo stat")
        ),
        patch.object(
            pathlib.Path, "is_file", side_effect=AssertionError("Unexpected photo stat")
        ),
    ):
        # hidden_fields deliberately follows photo in the input mapping.
        model = Cv.model_validate(
            {"photo": photo, "hidden_fields": ["photo"]}, context=context
        )
    if photo.startswith("https:"):
        assert isinstance(model.photo, pydantic.HttpUrl)
        assert str(model.photo) == photo
    else:
        assert model.photo == tmp_path / photo
    restored = Cv.model_validate_json(model.model_dump_json(), context=context)
    assert restored.photo == model.photo


@pytest.mark.parametrize(
    "photo",
    [
        [],
        {},
        42,
        True,
        "",
        "  ",
        "bad\0.png",
        "https://",
        "ftp://example.com/photo.png",
    ],
)
def test_hidden_photo_keeps_type_and_format_validation(photo):
    with pytest.raises(pydantic.ValidationError) as error:
        Cv(photo=photo, hidden_fields=["photo"])
    assert error.value.errors()[0]["loc"][0] == "photo"


def test_unhiding_photo_restores_resource_validation(tmp_path):
    source = {"cv": {"photo": "missing.png", "hidden_fields": ["photo"]}}
    _, model = build_rendercv_dictionary_and_model(
        json.dumps(source), input_file_path=tmp_path / "cv.yaml"
    )
    assert model.cv.photo == tmp_path / "missing.png"
    source["cv"]["hidden_fields"] = []
    with pytest.raises(RenderCVUserValidationError) as error:
        build_rendercv_dictionary_and_model(
            json.dumps(source), input_file_path=tmp_path / "cv.yaml"
        )
    assert all(
        item.schema_location == ("cv", "photo")
        for item in error.value.validation_errors
    )


def test_hidden_field_error_retains_yaml_position():
    with pytest.raises(RenderCVUserValidationError) as error:
        build_rendercv_dictionary_and_model("cv:\n  hidden_fields:\n    - unknown\n")
    diagnostic = error.value.validation_errors[0]
    assert diagnostic.schema_location == ("cv", "hidden_fields", "0")
    assert diagnostic.yaml_location is not None
    assert diagnostic.yaml_location[0][0] == 3


def test_schema_advertises_exact_hidden_field_protocol():
    schema = generate_json_schema()
    field = schema["$defs"]["Cv"]["properties"]["hidden_fields"]
    assert field["type"] == "array"
    assert field["default"] == []
    items = field["items"]
    if "$ref" in items:
        items = schema["$defs"][items["$ref"].rsplit("/", 1)[-1]]
    assert items["type"] == "string"
    assert set(items["enum"]) == set(FIELDS)


@pytest.mark.parametrize(
    "url", ["https:example.com/photo.png", "https:/example.com/photo.png"]
)
def test_hidden_http_urls_keep_normal_url_parsing(url):
    model = Cv(photo=url, hidden_fields=["photo"])
    assert isinstance(model.photo, pydantic.HttpUrl)
    assert str(model.photo) == "https://example.com/photo.png"


@pytest.mark.parametrize("url", ["https:", "http:"])
def test_hidden_photo_rejects_http_urls_without_a_host(url):
    with pytest.raises(pydantic.ValidationError):
        Cv(photo=url, hidden_fields=["photo"])
