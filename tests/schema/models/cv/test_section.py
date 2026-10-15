import copy
import json

import pydantic
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rendercv.exception import RenderCVUserValidationError
from rendercv.schema.json_schema_generator import generate_json_schema
from rendercv.schema.models.cv.cv import Cv

# They are called dynamically in the test with `eval(f"{entry_type}(**entry)")`.
from rendercv.schema.models.cv.entries.bullet import BulletEntry  # NOQA: F401
from rendercv.schema.models.cv.entries.education import EducationEntry  # NOQA: F401
from rendercv.schema.models.cv.entries.experience import ExperienceEntry  # NOQA: F401
from rendercv.schema.models.cv.entries.normal import NormalEntry  # NOQA: F401
from rendercv.schema.models.cv.entries.one_line import OneLineEntry  # NOQA: F401
from rendercv.schema.models.cv.entries.publication import PublicationEntry  # NOQA: F401
from rendercv.schema.models.cv.entries.text import TextEntry
from rendercv.schema.models.cv.section import (
    Section,
    SectionWithVisibility,
    available_entry_models,
    dictionary_key_to_proper_section_title,
    get_entry_type_name_and_section_model,
    get_rendercv_sections,
    validate_section,
)
from rendercv.schema.rendercv_model_builder import build_rendercv_dictionary_and_model
from rendercv.schema.sample_generator import rendercv_model_to_dictionary


@pytest.mark.parametrize(
    ("entry", "expected_entry_type", "expected_section_type"),
    [
        (
            "publication_entry",
            "PublicationEntry",
            "SectionWithPublicationEntries",
        ),
        (
            "experience_entry",
            "ExperienceEntry",
            "SectionWithExperienceEntries",
        ),
        (
            "education_entry",
            "EducationEntry",
            "SectionWithEducationEntries",
        ),
        (
            "normal_entry",
            "NormalEntry",
            "SectionWithNormalEntries",
        ),
        ("one_line_entry", "OneLineEntry", "SectionWithOneLineEntries"),
        ("text_entry", "TextEntry", "SectionWithTextEntries"),
        ("bullet_entry", "BulletEntry", "SectionWithBulletEntries"),
    ],
)
def test_get_entry_type_name_and_section_model(
    entry, expected_entry_type, expected_section_type, request: pytest.FixtureRequest
):
    entry = request.getfixturevalue(entry)
    entry_type, SectionModel = get_entry_type_name_and_section_model(entry)
    assert entry_type == expected_entry_type
    assert SectionModel.__name__ == expected_section_type

    # Initialize the entry with the entry type to test with model instances too
    if entry_type != "TextEntry":
        entry = eval(f"{entry_type}(**entry)")
        entry_type, SectionModel = get_entry_type_name_and_section_model(entry)
        assert entry_type == expected_entry_type
        assert SectionModel.__name__ == expected_section_type


@pytest.mark.parametrize(
    "EntryType",
    available_entry_models,
)
def test_entries_with_extra_attributes(EntryType, request: pytest.FixtureRequest):
    # Get the name of the class:
    entry_type_name: str = EntryType.__name__

    # Convert from camel case to snake case
    entry_type_name = "".join(
        ["_" + c.lower() if c.isupper() else c for c in entry_type_name]
    ).lstrip("_")

    # Get entry contents from fixture:
    entry_contents = request.getfixturevalue(entry_type_name)

    entry_contents["extra_attribute"] = "extra value"

    entry = EntryType(**entry_contents)

    assert entry.extra_attribute == "extra value"


@pytest.mark.parametrize(
    ("key", "expected_section_title"),
    [
        ("this_is_a_test", "This Is a Test"),
        ("welcome_to_rendercv!", "Welcome to Rendercv!"),
        ("Welcome to RenderCV!", "Welcome to RenderCV!"),
        ("\\faGraduationCap_education", "\\faGraduationCap_education"),
        ("\\faGraduationCap Education", "\\faGraduationCap Education"),
        ("Hello_World", "Hello_World"),
        ("Hello World", "Hello World"),
    ],
)
def test_dictionary_key_to_proper_section_title(key, expected_section_title):
    assert dictionary_key_to_proper_section_title(key) == expected_section_title


class TestDictionaryKeyToProperSectionTitle:
    @settings(deadline=None)
    @given(
        key=st.from_regex(r"[a-z]{1,5}(_[a-z]{1,5}){0,3}", fullmatch=True),
    )
    def test_snake_case_replaces_underscores_with_spaces(self, key: str) -> None:
        result = dictionary_key_to_proper_section_title(key)
        assert "_" not in result
        assert " " in result or len(key.split("_")) == 1

    @settings(deadline=None)
    @given(
        parts=st.lists(
            st.from_regex(r"[a-zA-Z0-9]{1,10}", fullmatch=True),
            min_size=2,
            max_size=5,
        )
    )
    def test_keys_with_spaces_returned_unchanged(self, parts: list[str]) -> None:
        key = " ".join(parts)
        assert dictionary_key_to_proper_section_title(key) == key

    @settings(deadline=None)
    @given(
        key=st.from_regex(r"[a-zA-Z]*[A-Z][a-zA-Z]*", fullmatch=True).filter(
            lambda s: " " not in s and len(s) <= 30
        )
    )
    def test_keys_with_uppercase_returned_unchanged(self, key: str) -> None:
        assert dictionary_key_to_proper_section_title(key) == key


def test_section_rejects_none_entries():
    section_adapter = pydantic.TypeAdapter[Section](Section)
    with pytest.raises(pydantic.ValidationError):
        section_adapter.validate_python([None])


def test_section_accepts_empty_list():
    section_adapter = pydantic.TypeAdapter[Section](Section)
    result = section_adapter.validate_python([])
    assert result == []


@pytest.mark.parametrize("entry_type", available_entry_models)
def test_structured_entry_flags_survive_serialization(entry_type, request):
    fixture_name = "".join(
        "_" + c.lower() if c.isupper() else c for c in entry_type.__name__
    ).lstrip("_")
    entry = request.getfixturevalue(fixture_name)
    original = copy.deepcopy(entry)
    model = Cv.model_validate(
        {"sections": {"Entries": [entry, {**entry, "hidden": True}]}}
    )

    visible = model.rendercv_sections[0].entries
    assert len(visible) == 1
    assert visible[0].hidden is False
    saved = model.model_dump(mode="json")
    assert "hidden" not in saved["sections"]["Entries"][0]
    assert saved["sections"]["Entries"][1]["hidden"] is True
    restored = Cv.model_validate(saved)
    assert restored.sections is not None
    restored_entries = restored.sections["Entries"]
    assert isinstance(restored_entries, list)
    assert len(restored_entries) == 2
    assert len(restored.rendercv_sections[0].entries) == 1
    assert entry == original


def test_section_and_mixed_text_inputs_preserve_full_data():
    raw = {
        "sections": {
            "Summary": [
                "Plain",
                {"text": "Secret", "hidden": True},
                {"text": "Visible", "hidden": False},
            ],
            "Education": {
                "hidden": True,
                "entries": [
                    {"institution": "A", "area": "CS"},
                    {"institution": "B", "area": "Math", "hidden": True},
                ],
            },
            "Empty": [],
            "All hidden": [{"bullet": "Secret", "hidden": True}],
        }
    }
    before = copy.deepcopy(raw)
    model = Cv.model_validate(raw)
    assert [section.title for section in model.rendercv_sections] == [
        "Summary",
        "Empty",
    ]
    assert model.rendercv_sections[0].entries == ["Plain", "Visible"]
    assert model.sections is not None
    summary = model.sections["Summary"]
    assert isinstance(summary, list)
    assert isinstance(summary[1], TextEntry)
    assert summary[1].hidden is True
    assert isinstance(model.sections["Education"], SectionWithVisibility)
    restored = Cv.model_validate_json(model.model_dump_json())
    assert restored.sections is not None
    education = restored.sections["Education"]
    assert isinstance(education, SectionWithVisibility)
    education.hidden = False
    assert [section.title for section in restored.rendercv_sections] == [
        "Summary",
        "Education",
        "Empty",
    ]
    assert [entry.institution for entry in restored.rendercv_sections[1].entries] == [
        "A"
    ]
    assert raw == before


@pytest.mark.parametrize(
    ("section", "path", "line"),
    [
        (
            "    Notes:\n      hidden: perhaps\n      entries: [Valid]\n",
            ("Notes", "hidden"),
            4,
        ),
        (
            "    Notes:\n      - bullet: Valid\n        hidden: perhaps\n",
            ("Notes", "0", "hidden"),
            5,
        ),
        (
            """    Notes:
      entries:
        - text: Valid
          hidden: perhaps
""",
            ("Notes", "entries", "0", "hidden"),
            6,
        ),
        ("    Notes:\n      hidden: false\n", ("Notes", "entries"), 3),
        (
            "    Notes:\n      entries: [Valid]\n      unknown: true\n",
            ("Notes", "unknown"),
            5,
        ),
        ("    Notes:\n      - text: [Invalid]\n", ("Notes", "0", "text"), 4),
    ],
)
def test_extended_input_errors_point_at_original_yaml(section, path, line):
    with pytest.raises(RenderCVUserValidationError) as caught:
        build_rendercv_dictionary_and_model("cv:\n  sections:\n" + section)
    error = next(
        error
        for error in caught.value.validation_errors
        if error.schema_location == ("cv", "sections", *path)
    )
    assert error.yaml_location is not None
    assert error.yaml_location[0][0] == line


def test_hidden_content_is_validated_without_reindexing():
    source = """cv:
  sections:
    Work:
      hidden: true
      entries:
        - name: First
          hidden: true
        - name: Second
        - name: Invalid hidden draft
          hidden: true
          start_date: invalid
"""
    with pytest.raises(RenderCVUserValidationError) as caught:
        build_rendercv_dictionary_and_model(source)
    error = next(
        error
        for error in caught.value.validation_errors
        if error.schema_location and error.schema_location[-1] == "start_date"
    )
    assert error.schema_location == (
        "cv",
        "sections",
        "Work",
        "entries",
        "2",
        "start_date",
    )
    assert error.yaml_location is not None
    assert error.yaml_location[0][0] == 11


def test_hidden_does_not_disable_homogeneous_entry_validation():
    with pytest.raises(pydantic.ValidationError):
        Cv.model_validate(
            {
                "sections": {
                    "Work": {
                        "hidden": True,
                        "entries": [
                            {"name": "Project"},
                            {"bullet": "Wrong type", "hidden": True},
                        ],
                    }
                }
            }
        )
    # A legacy custom text field must not change the inferred structured type.
    model = Cv.model_validate(
        {"sections": {"Work": [{"name": "Project", "text": "Extra", "hidden": True}]}}
    )
    assert model.model_dump()["sections"]["Work"][0]["name"] == "Project"


def test_yaml_export_retains_flags_and_hidden_content():
    source = """cv:
  sections:
    Work:
      hidden: true
      entries:
        - name: Secret
          hidden: true
    Copy:
      hidden: true
      entries:
        - name: Secret
          hidden: true
    Notes:
      - text: Visible
      - text: Visible
"""
    original, model = build_rendercv_dictionary_and_model(source)
    before = copy.deepcopy(original)
    exported = rendercv_model_to_dictionary(model)
    assert exported["cv"]["sections"]["Work"]["hidden"] is True
    assert exported["cv"]["sections"]["Copy"]["entries"][0]["name"] == "Secret"
    assert [section.entries for section in model.cv.rendercv_sections] == [
        ["Visible", "Visible"]
    ]
    assert original == before
    assert len(json.loads(model.model_dump_json())["cv"]["sections"]) == 3


def test_schema_describes_both_section_forms_and_text_visibility():
    definitions = generate_json_schema()["$defs"]
    section_refs = {item["$ref"] for item in definitions["Section"]["anyOf"]}
    assert section_refs == {"#/$defs/ListOfEntries", "#/$defs/SectionWithVisibility"}
    assert definitions["SectionWithVisibility"]["required"] == ["entries"]
    expected_types = {
        "TextEntry",
        "OneLineEntry",
        "NormalEntry",
        "ExperienceEntry",
        "EducationEntry",
        "PublicationEntry",
        "BulletEntry",
        "NumberedEntry",
        "ReversedNumberedEntry",
    }
    # Resolve the actual entry references used by ListOfEntries. Do not filter
    # by presence of hidden: that would silently skip exactly the missing field.
    names = set()

    def collect_names(value):
        if isinstance(value, dict):
            if "$ref" in value:
                name = value["$ref"].rsplit("/", 1)[-1]
                if name.endswith("Entry"):
                    names.add(name)
                else:
                    collect_names(definitions[name])
            for key, nested in value.items():
                if key != "$ref":
                    collect_names(nested)
        elif isinstance(value, list):
            for nested in value:
                collect_names(nested)

    collect_names(definitions["ListOfEntries"])
    assert {name.rsplit("__", 1)[-1] for name in names} == expected_types
    for name in names | {"SectionWithVisibility"}:
        hidden = definitions[name]["properties"]["hidden"]
        assert hidden["type"] == "boolean"
        assert hidden["default"] is False
    assert definitions["TextEntry"]["required"] == ["text"]


@pytest.mark.parametrize("title", ["2024", "industry", "list"])
def test_hidden_flag_errors_keep_arbitrary_section_titles(title):
    source = f"""cv:
  sections:
    '{title}':
      hidden: invalid
      entries: [Text]
"""
    with pytest.raises(RenderCVUserValidationError) as caught:
        build_rendercv_dictionary_and_model(source)
    error = caught.value.validation_errors[0]
    assert error.schema_location == ("cv", "sections", title, "hidden")
    assert error.yaml_location is not None
    assert error.yaml_location[0] == (4, 7)


def test_direct_validator_keeps_legacy_call_signature():

    assert validate_section(["Text"]) == ["Text"]
    assert validate_section([{"name": "Project"}])[0].name == "Project"
    wrapped = validate_section({"hidden": True, "entries": [{"text": "Text"}]})
    assert wrapped.hidden is True
    assert wrapped.entries[0].text == "Text"


def test_raw_dictionary_projection_preserves_legacy_representation():

    raw = {
        "Work": [{"name": "Project", "text": "Custom field"}],
        "Notes": [
            "Plain",
            {"text": "Visible", "hidden": "false"},
            {"text": "Hidden", "hidden": "true"},
        ],
        "Archived": {"hidden": "true", "entries": [{"bullet": "Hidden"}]},
        "Wrapped": {
            "entries": [{"name": "Visible"}, {"name": "Hidden", "hidden": True}]
        },
    }
    before = copy.deepcopy(raw)
    sections = get_rendercv_sections(raw)
    assert [(section.title, section.entries) for section in sections] == [
        ("Work", [{"name": "Project", "text": "Custom field"}]),
        ("Notes", ["Plain", "Visible"]),
        ("Wrapped", [{"name": "Visible"}]),
    ]
    assert raw == before


@pytest.mark.parametrize("wrapped", [False, True])
def test_optional_validator_context_does_not_drop_render_date(wrapped):
    entries = [{"name": "Future work", "start_date": 2090, "end_date": "present"}]
    content = {"entries": entries} if wrapped else entries
    _, model = build_rendercv_dictionary_and_model(
        json.dumps(
            {
                "cv": {"sections": {"Work": content}},
                "settings": {"current_date": "2100-01-01"},
            }
        )
    )
    assert model.cv.rendercv_sections[0].entries[0].start_date == 2090
    with pytest.raises(RenderCVUserValidationError) as caught:
        build_rendercv_dictionary_and_model(
            json.dumps(
                {
                    "cv": {"sections": {"Work": content}},
                    "settings": {"current_date": "1999-01-01"},
                }
            )
        )
    assert any(
        "cannot be after" in issue.message for issue in caught.value.validation_errors
    )
