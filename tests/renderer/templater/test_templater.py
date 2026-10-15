import copy
import json
import subprocess
import sys
from typing import Literal

import pytest

from rendercv.renderer.templater.entry_templates_from_input import (
    render_entry_templates,
)
from rendercv.renderer.templater.model_processor import process_fields, process_model
from rendercv.renderer.templater.templater import render_full_template
from rendercv.schema.models.cv.entries.normal import NormalEntry
from rendercv.schema.models.cv.section import SectionWithVisibility
from rendercv.schema.models.design.built_in_design import available_themes
from rendercv.schema.models.rendercv_model import RenderCVModel
from rendercv.schema.rendercv_model_builder import build_rendercv_dictionary_and_model

FORMATS: tuple[Literal["typst", "markdown"], ...] = ("typst", "markdown")


def documents(theme="classic"):
    visible_entries = [
        "VisibleText",
        {"name": "VisibleNormal"},
        {"institution": "VisibleEducation", "area": "CS"},
        {"company": "VisibleExperience", "position": "Engineer"},
        {"title": "VisiblePublication", "authors": ["Author"], "date": "2020-01"},
        {"label": "VisibleOneLine", "details": "Details"},
        {"bullet": "VisibleBullet"},
        {"number": "VisibleNumbered"},
        {"reversed_number": "VisibleReverse"},
    ]
    extended, expected = {}, {}
    for index, entry in enumerate(visible_entries):
        hidden = {
            "hidden": True,
            **(
                {"text": "SecretText"}
                if isinstance(entry, str)
                else json.loads(json.dumps(entry).replace("Visible", "Secret"))
            ),
        }
        shown = (
            {"text": entry, "hidden": False}
            if isinstance(entry, str)
            else {**entry, "hidden": False}
        )
        entries = [hidden, shown, copy.deepcopy(shown)]
        extended[f"Section {index}"] = (
            entries if index % 2 else {"hidden": False, "entries": entries}
        )
        expected[f"Section {index}"] = [copy.deepcopy(entry), copy.deepcopy(entry)]
    extended["HiddenSection"] = {"hidden": True, "entries": [{"name": "SecretSection"}]}
    extended["AllHidden"] = {"entries": [{"bullet": "SecretOnly", "hidden": True}]}

    def wrap(sections):
        return {
            "cv": {"name": "Visibility", "sections": sections},
            "design": {"theme": theme},
            "settings": {"current_date": "2026-10-15"},
        }

    return wrap(extended), wrap(expected)


@pytest.mark.parametrize("theme", available_themes)
def test_all_entry_types_match_visible_only_documents_in_every_theme(theme):
    extended, expected = documents(theme)
    model = RenderCVModel.model_validate(extended)
    reference = RenderCVModel.model_validate(expected)
    original = model.cv.model_dump_json()
    for file_type in FORMATS:
        output = render_full_template(model, file_type)
        assert output == render_full_template(reference, file_type)
        assert "Secret" not in output
        assert "HiddenSection" not in output
        assert "AllHidden" not in output
    assert model.cv.model_dump_json() == original


def test_visibility_changes_are_used_even_after_cached_view_was_read():
    model = RenderCVModel.model_validate(
        {
            "cv": {
                "sections": {
                    "Work": {
                        "entries": [
                            {"name": "First"},
                            {"name": "Second", "hidden": True},
                        ]
                    }
                }
            }
        }
    )
    assert len(model.cv.rendercv_sections[0].entries) == 1
    assert model.cv.sections is not None
    section = model.cv.sections["Work"]
    assert isinstance(section, SectionWithVisibility)
    first, second = section.entries
    assert isinstance(first, NormalEntry)
    assert isinstance(second, NormalEntry)
    first.hidden = True
    second.hidden = False
    for file_type in FORMATS:
        output = render_full_template(model, file_type)
        assert "First" not in output
        assert "Second" in output
    section.hidden = True
    assert "Second" not in render_full_template(model, "markdown")
    section.hidden = False
    assert "Second" in render_full_template(model, "markdown")


def test_visibility_metadata_is_not_processed_as_text_or_a_template_field():
    model = RenderCVModel.model_validate({"cv": {"name": "Probe"}})
    entry = NormalEntry(name="Example", hidden=True)
    render_entry_templates(
        entry,
        templates=model.design.templates,
        locale=model.locale,
        show_time_span=False,
        current_date=model.settings._resolved_current_date,
    )
    process_fields(entry, [lambda text: text.upper()])
    assert entry.hidden is True
    assert "HIDDEN" not in (entry.model_extra or {})
    assert entry.name == "EXAMPLE"


def test_cli_renders_same_yaml_to_all_formats_and_preserves_source(tmp_path):
    extended, _ = documents()
    source = tmp_path / "visibility.yaml"
    source.write_text(json.dumps(extended), encoding="utf-8")
    original = source.read_bytes()
    output = tmp_path / "rendered"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rendercv",
            "render",
            str(source),
            "--output-folder",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert source.read_bytes() == original
    for suffix in ["typ", "md", "html", "pdf", "png"]:
        assert list(output.glob("*." + suffix)), (suffix, result.stdout)
    for suffix in ["typ", "md", "html"]:
        rendered = next(output.glob("*." + suffix)).read_text(encoding="utf-8")
        assert "Secret" not in rendered
        assert "VisibleNormal" in rendered
    assert next(output.glob("*.pdf")).read_bytes().startswith(b"%PDF")
    assert next(output.glob("*.png")).read_bytes().startswith(b"\x89PNG")

    # CLI overrides are strings; false must unhide the parent without erasing
    # child flags. This is the same model builder used by browser workers.
    source_text = """cv:
  sections:
    Work:
      hidden: true
      entries:
        - name: Visible
        - name: Secret
          hidden: true
"""
    _, model = build_rendercv_dictionary_and_model(
        source_text, overrides={"cv.sections.Work.hidden": "false"}
    )
    rendered = render_full_template(model, "markdown")
    assert "Visible" in rendered
    assert "Secret" not in rendered


def test_prepared_output_is_separate_from_live_source_view():

    model = RenderCVModel.model_validate(
        {
            "cv": {
                "sections": {
                    "Work *heading*": {
                        "entries": [{"name": "A *project*"}],
                    }
                }
            }
        }
    )
    source_json = model.cv.model_dump_json()
    prepared = process_model(model, "typst")
    assert prepared.cv.rendercv_sections[0].title == "Work #emph[heading]"
    assert prepared.cv.rendercv_sections[0].entries[0].name == "A #emph[project]"
    assert model.cv.rendercv_sections[0].title == "Work *heading*"
    assert model.cv.model_dump_json() == source_json
    assert model.cv.sections is not None
    section = model.cv.sections["Work *heading*"]
    assert isinstance(section, SectionWithVisibility)
    section.hidden = True
    assert model.cv.rendercv_sections == []
    assert prepared.cv.rendercv_sections[0].title == "Work #emph[heading]"
