import copy
import json
import shutil
import struct
import subprocess
import zlib
from typing import Literal
from unittest.mock import patch

import pydantic
import pytest

from rendercv.cli.render_command.run_rendercv import collect_input_file_paths
from rendercv.exception import RenderCVUserError
from rendercv.renderer.html import generate_html
from rendercv.renderer.markdown import generate_markdown
from rendercv.renderer.pdf_png import generate_pdf, generate_png
from rendercv.renderer.templater.connections import parse_connections
from rendercv.renderer.templater.markdown_parser import markdown_to_typst
from rendercv.renderer.templater.model_processor import (
    download_photo_from_url,
    process_model,
)
from rendercv.renderer.templater.name_placeholder import remove_name_placeholder
from rendercv.renderer.templater.templater import render_full_template, render_html
from rendercv.renderer.typst import copy_photo_next_to_typst_file, generate_typst
from rendercv.schema.models.design.built_in_design import available_themes
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


FORMATS: tuple[Literal["typst", "markdown"], ...] = ("typst", "markdown")


def png_bytes():
    def chunk(kind, data):
        return (
            struct.pack("!I", len(data))
            + kind
            + data
            + struct.pack("!I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0\x12\x34\x56"))
        + chunk(b"IEND", b"")
    )


def rendered_pngs(model):
    typst_path = generate_typst(model)
    assert typst_path is not None
    paths = generate_png(model, typst_path)
    assert paths
    return [path.read_bytes() for path in paths]


@pytest.fixture
def document(tmp_path):
    photo = tmp_path / "placeholder.png"
    photo.write_bytes(png_bytes())
    return {
        "cv": {
            "name": "Example Candidate",
            "headline": "Example Headline",
            "location": "Example City",
            "photo": str(photo),
            "website": ["https://example.com/first", "https://example.com/second"],
            "email": ["first@example.com", "second@example.com"],
            "phone": ["+12025550123", "+12025550124"],
            "social_networks": [
                {"network": "GitHub", "username": "example-placeholder"}
            ],
            "custom_connections": [
                {
                    "fontawesome_icon": "link",
                    "placeholder": "Example Contact",
                    "url": "https://example.com/contact",
                }
            ],
            "sections": {
                "Summary": [
                    "Visible body content",
                    {"text": "Hidden entry content", "hidden": True},
                ],
                "Archive": {"hidden": True, "entries": ["Hidden section content"]},
            },
        },
        "settings": {
            "current_date": "2024-01-15",
            "render_command": {"output_folder": str(tmp_path / "output")},
        },
    }


def model_from(source, tmp_path):
    return build_rendercv_dictionary_and_model(
        json.dumps(source), input_file_path=tmp_path / "cv.yaml"
    )[1]


@pytest.mark.parametrize(
    "hidden",
    [[field] for field in FIELDS]
    + [
        FIELDS,
        ["email", "phone", "website"],
        ["name", "photo"],
        ["social_networks", "custom_connections", "location"],
    ],
)
@pytest.mark.parametrize("theme", available_themes)
def test_hidden_fields_match_omitted_content_across_themes(
    document, tmp_path, hidden, theme
):
    document["design"] = {"theme": theme}
    document["cv"]["hidden_fields"] = hidden
    source = model_from(document, tmp_path)
    before, order = source.model_dump_json(), list(source.cv._key_order)
    omitted = copy.deepcopy(document)
    omitted["cv"].pop("hidden_fields")
    for field in hidden:
        omitted["cv"].pop(field)
    if "name" in hidden:
        omitted["cv"]["hidden_fields"] = ["name"]
        omitted["design"]["templates"] = {"footer": "*PAGE_NUMBER/TOTAL_PAGES*"}
        omitted["settings"]["pdf_title"] = "CV"
    expected = model_from(omitted, tmp_path)
    for fmt in FORMATS:
        actual = render_full_template(source, fmt)
        assert actual == render_full_template(expected, fmt)
        assert "Hidden section content" not in actual
        assert "Hidden entry content" not in actual
        assert "None" not in actual
    assert render_html(source, render_full_template(source, "markdown")) == render_html(
        expected, render_full_template(expected, "markdown")
    )
    assert source.model_dump_json() == before
    assert source.cv._key_order == order
    assert source.cv._rendered_sections is None


def test_contact_order_and_whole_lists_are_preserved_when_toggling(document, tmp_path):
    model = model_from(document, tmp_path)
    visible = render_full_template(model, "typst")
    for _ in range(3):
        model.cv.hidden_fields[:] = ["email", "phone", "social_networks"]
        original = model.model_dump_json()
        processed = process_model(model, "typst")
        assert processed.cv._key_order == [
            key for key in model.cv._key_order if key not in model.cv.hidden_fields
        ]
        assert [item.body for item in parse_connections(processed)] == [
            "Example City",
            "example.com/first",
            "example.com/second",
            "Example Contact",
        ]
        hidden = render_full_template(model, "typst")
        assert "mailto:" not in hidden
        assert "tel:" not in hidden
        assert "github.com" not in hidden
        assert model.model_dump_json() == original
        model.cv.hidden_fields.clear()
        assert render_full_template(model, "typst") == visible


@pytest.mark.parametrize(
    "photo", ["missing.png", "https://example.invalid/unreachable.png"]
)
def test_hidden_photo_never_reaches_resource_helpers(document, tmp_path, photo):
    document["cv"]["photo"] = photo
    document["cv"]["hidden_fields"] = ["photo"]
    model = model_from(document, tmp_path)
    original = model.model_dump_json()
    with (
        patch(
            "urllib.request.urlopen", side_effect=AssertionError("Unexpected download")
        ),
        patch("shutil.copy", side_effect=AssertionError("Unexpected photo copy")),
    ):
        download_photo_from_url(model)
        copy_photo_next_to_typst_file(model, tmp_path / "copy.typ")
        typst_path = generate_typst(model)
        assert typst_path is not None
        assert "#grid(" not in typst_path.read_text()
        assert "#pad(left:" not in typst_path.read_text()
        pdf = generate_pdf(model, typst_path)
        assert pdf is not None
        assert pdf.exists()
        assert generate_png(model, typst_path)
        md = generate_markdown(model)
        html = generate_html(model, md)
        assert html is not None
        assert html.exists()
    assert model.model_dump_json() == original
    assert not (tmp_path / "output" / "missing.png").exists()
    assert not (tmp_path / "output" / "unreachable.png").exists()
    model.cv.hidden_fields.clear()
    with (
        patch(
            "urllib.request.urlopen",
            side_effect=OSError("Unavailable placeholder server"),
        ),
        pytest.raises(RenderCVUserError),
    ):
        render_full_template(model, "typst")


@pytest.mark.parametrize("theme", available_themes)
def test_hidden_photo_has_exactly_the_existing_no_photo_layout(
    document, tmp_path, theme
):
    document["design"] = {"theme": theme}
    document["cv"]["hidden_fields"] = ["photo"]
    hidden = model_from(document, tmp_path)
    hidden_png = rendered_pngs(hidden)
    omitted = copy.deepcopy(document)
    omitted["cv"].pop("photo")
    omitted["cv"].pop("hidden_fields")
    shown = model_from(omitted, tmp_path)
    assert hidden_png == rendered_pngs(shown)


def test_visible_url_download_does_not_replace_photo_on_source_model(
    document, tmp_path
):
    document["cv"]["photo"] = "https://example.invalid/placeholder.png"
    model = model_from(document, tmp_path)
    original = model.model_dump_json()
    with patch("urllib.request.urlopen") as request:
        request.return_value.__enter__.return_value.read.return_value = png_bytes()
        typst_path = generate_typst(model)
    assert request.call_count == 1
    assert typst_path is not None
    assert (typst_path.parent / "placeholder.png").read_bytes() == png_bytes()
    assert isinstance(model.cv.photo, pydantic.HttpUrl)
    assert model.model_dump_json() == original
    with patch("urllib.request.urlopen", side_effect=AssertionError("Hidden download")):
        model.cv.hidden_fields[:] = ["photo"]
        assert "#grid(" not in render_full_template(model, "typst")


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("*NAME -- PAGE_NUMBER/TOTAL_PAGES*", "*PAGE_NUMBER/TOTAL_PAGES*"),
        ("**NAME** | CURRENT_DATE", "CURRENT_DATE"),
        ("CURRENT_DATE — NAME", "CURRENT_DATE"),
        ("LAST_UPDATED CURRENT_DATE by NAME", "LAST_UPDATED CURRENT_DATE by"),
        ("**NAME**", ""),
        ("__NAME__", ""),
        ("_NAME -- PAGE_NUMBER/TOTAL_PAGES_", "_PAGE_NUMBER/TOTAL_PAGES_"),
        ("_CURRENT_DATE -- NAME_", "_CURRENT_DATE_"),
        ("MONTH_NAME, YEAR", "MONTH_NAME, YEAR"),
        ("_MONTH_NAME_", "_MONTH_NAME_"),
        ("___CV__ | MONTH_NAME", "___CV__ | MONTH_NAME"),
        ("___CV__ | MONTH_NAME | YEAR", "___CV__ | MONTH_NAME | YEAR"),
        ("` `` | MONTH_NAME", "` `` | MONTH_NAME"),
        ("` ``` | MONTH_NAME", "` ``` | MONTH_NAME"),
        ("A -- NAME -- B", "A -- B"),
        ("(NAME) | YEAR", "YEAR"),
        ("NAME -- MONTH_NAME, YEAR", "MONTH_NAME, YEAR"),
        (
            "NAME -- for internal use only -- PAGE_NUMBER",
            "for internal use only -- PAGE_NUMBER",
        ),
        (
            "MONTH_NAME | SURNAME | NAME_SUFFIX | NAME2 | FULLNAME",
            "MONTH_NAME | SURNAME | NAME_SUFFIX | NAME2 | FULLNAME",
        ),
        (
            "NAME -- MONTH_NAME | SURNAME | NAME_SUFFIX",
            "MONTH_NAME | SURNAME | NAME_SUFFIX",
        ),
        (
            "NAME -- keep  custom\tspacing -- PAGE_NUMBER",
            "keep  custom\tspacing -- PAGE_NUMBER",
        ),
        ("**NAME's CV** | PAGE_NUMBER", "**CV** | PAGE_NUMBER"),
        ("**NAME’s CV** | PAGE_NUMBER", "**CV** | PAGE_NUMBER"),
        ("_NAME's CV_ | PAGE_NUMBER", "_CV_ | PAGE_NUMBER"),
        ("__NAME's CV__ | PAGE_NUMBER", "__CV__ | PAGE_NUMBER"),
        ("***NAME's CV*** | PAGE_NUMBER", "***CV*** | PAGE_NUMBER"),
        ("NAME -- **Custom  text** | PAGE_NUMBER", "**Custom  text** | PAGE_NUMBER"),
        ("**NAME** | **Keep  spaces**", "**Keep  spaces**"),
        ("_NAME_ -- PAGE_NUMBER", "PAGE_NUMBER"),
        ("***NAME***", ""),
        ("___NAME___", ""),
        ("___NAME_CV___", "___NAME_CV___"),
        ("prefix**NAME**suffix", "prefixsuffix"),
        ("**NAME**CV", "CV"),
        ("**NAME**_MONTH_NAME_", "_MONTH_NAME_"),
        ("**NAME**’s CV", "CV"),
        ("  **NAME**  ", ""),
        ("***NAME** CV* | PAGE_NUMBER", "*CV* | PAGE_NUMBER"),
        ("***NAME* CV**", "**CV**"),
        ("**NAME *CV***", "***CV***"),
        ("**CV *NAME***", "**CV**"),
        ("___NAME_ CV__", "__CV__"),
        ("__NAME _CV___", "___CV___"),
        (
            r"[NAME's \[CV\]](https://example.com/NAME)",
            r"[\[CV\]](https://example.com/NAME)",
        ),
        (
            r"[NAME's CV](https://example.com/profile_\(candidate\))",
            r"[CV](https://example.com/profile_\(candidate\))",
        ),
        (
            r"[Reference \[CV\]](https://example.com/NAME)",
            r"[Reference \[CV\]](https://example.com/NAME)",
        ),
        ("`**NAME** CV`", "`**** CV`"),
        ("MONTH_NAME | ` `", "MONTH_NAME | ` `"),
        (
            "MONTH_NAME | [ ](https://example.com)",
            "MONTH_NAME | [ ](https://example.com)",
        ),
        (
            "MONTH_NAME | [](https://example.com)",
            "MONTH_NAME | [](https://example.com)",
        ),
        (r"MONTH\_NAME", r"MONTH\_NAME"),
        (r"NAME\_SUFFIX", r"NAME\_SUFFIX"),
        (r"**MONTH\_NAME**", r"**MONTH\_NAME**"),
        (
            "![NAME](https://example.com/photo.png)",
            "![](https://example.com/photo.png)",
        ),
        ("`(NAME)`", "`()`"),
        ("___NAME__ CV_ | PAGE_NUMBER", "_CV_ | PAGE_NUMBER"),
        ("__*NAME* CV__ | PAGE_NUMBER", "__CV__ | PAGE_NUMBER"),
        ("[NAME](https://example.com)", ""),
        ("[**NAME**](https://example.com)", ""),
        ('[*NAME*](https://example.com "Profile")', ""),
        ("[NAME](https://example.com/profile_(candidate))", ""),
        ("*[**NAME**](https://example.com)*", ""),
        (
            '[**NAME**](https://example.com "Profile") | MONTH_NAME, YEAR',
            "MONTH_NAME, YEAR",
        ),
        ("[NAME's CV](https://example.com)", "[CV](https://example.com)"),
        (
            '[**NAME\'s CV**](https://example.com "Profile")',
            '[**CV**](https://example.com "Profile")',
        ),
        (
            "[NAME's CV](https://example.com/profile_(candidate))",
            "[CV](https://example.com/profile_(candidate))",
        ),
        (
            "[NAME's CV](https://example.com/NAME?label=MONTH_NAME)",
            "[CV](https://example.com/NAME?label=MONTH_NAME)",
        ),
        (
            "[MONTH_NAME, YEAR](https://example.com/NAME)",
            "[MONTH_NAME, YEAR](https://example.com/NAME)",
        ),
        (
            "[NAME](https://example.com) -- for internal use only",
            "for internal use only",
        ),
        (
            "[NAME](https://example.com) -- [Reference](https://example.com/other)",
            "[Reference](https://example.com/other)",
        ),
    ],
)
def test_name_derived_templates_remove_only_name_and_adjacent_separators(
    document, tmp_path, template, expected
):
    document["cv"]["hidden_fields"] = ["name"]
    document["design"] = {
        "theme": "classic",
        "templates": {"footer": template, "top_note": template},
    }
    model = model_from(document, tmp_path)
    processed = process_model(model, "typst")
    assert processed.design.templates.footer == expected
    assert processed.design.templates.top_note == expected
    assert processed.settings.pdf_title == "CV"
    assert processed.cv._plain_name == ""
    if not expected:
        assert not processed.design.page.show_footer
        assert not processed.design.page.show_top_note
    assert model.design.templates.footer == template


@pytest.mark.skipif(
    not shutil.which("pdfinfo") or not shutil.which("pdftotext"),
    reason="Requires Poppler PDF inspection tools",
)
def test_hidden_name_is_removed_from_pdf_metadata_but_not_filenames_or_literal_body(
    document, tmp_path
):
    document["cv"]["hidden_fields"] = ["name", "photo"]
    model = model_from(document, tmp_path)
    typst_path = generate_typst(model)
    pdf = generate_pdf(model, typst_path)
    assert pdf is not None
    assert pdf.name == "Example_Candidate_CV.pdf"
    info = subprocess.run(
        ["pdfinfo", str(pdf)], capture_output=True, text=True, check=True
    ).stdout
    text = subprocess.run(
        ["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True
    ).stdout
    assert "Example Candidate" not in info + text
    assert "None" not in info + text
    assert "Title:           CV" in info
    document["cv"]["sections"]["Summary"] = ["Literal Example Candidate reference"]
    document["settings"]["pdf_title"] = "Literal Example Candidate title"
    literal = model_from(document, tmp_path)
    rendered = render_full_template(literal, "typst")
    assert "Literal Example Candidate reference" in rendered
    assert "Literal Example Candidate title" in rendered


@pytest.mark.skipif(
    not shutil.which("pdfinfo") or not shutil.which("pdftotext"),
    reason="Requires Poppler PDF inspection tools",
)
def test_hidden_name_preserves_dates_custom_text_and_markdown_in_pdf(
    document, tmp_path
):
    document["cv"]["hidden_fields"] = ["name", "photo"]
    document["settings"].update(
        current_date="2026-01-15",
        pdf_title="NAME -- MONTH_NAME, YEAR -- for internal use only",
    )
    document["design"] = {
        "theme": "classic",
        "page": {"show_footer": True, "show_top_note": True},
        "templates": {
            "footer": "**NAME's CV** | MONTH_NAME, YEAR | PAGE_NUMBER",
            "top_note": "NAME -- for internal use only -- MONTH_NAME, YEAR",
        },
    }
    model = model_from(document, tmp_path)
    original = model.model_dump_json()
    typst = generate_typst(model)
    assert typst is not None
    assert "#strong[CV]" in typst.read_text()
    pdf = generate_pdf(model, typst)
    assert pdf is not None
    info = subprocess.run(
        ["pdfinfo", str(pdf)], capture_output=True, text=True, check=True
    ).stdout
    text = subprocess.run(
        ["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True
    ).stdout
    title = next(line for line in info.splitlines() if line.startswith("Title:"))
    assert title.removeprefix("Title:").strip() == (
        "January, 2026 -- for internal use only"
    )
    assert "January, 2026" in text
    assert "for internal use only" in text
    assert "CV" in text
    assert "*" not in text
    assert "Example Candidate" not in info + text
    assert model.model_dump_json() == original


@pytest.mark.parametrize("fmt", FORMATS)
def test_hidden_name_keeps_other_identifiers_in_final_derived_content(
    document, tmp_path, fmt
):
    template = "NAME -- MONTH_NAME, YEAR | SURNAME | NAME_SUFFIX | NAME2 | FULLNAME"
    document["cv"]["hidden_fields"] = ["name"]
    document["settings"]["pdf_title"] = template
    document["design"] = {
        "theme": "classic",
        "templates": {"footer": template, "top_note": template},
    }
    model = model_from(document, tmp_path)
    original = model.model_dump_json()
    processed = process_model(model, fmt)
    expected = "January, 2024 | SURNAME | NAME_SUFFIX | NAME2 | FULLNAME"
    formatted = markdown_to_typst(expected) if fmt == "typst" else expected
    assert formatted in processed.cv._footer
    assert processed.cv._top_note == formatted
    assert processed.settings.pdf_title == expected
    assert model.model_dump_json() == original


@pytest.mark.parametrize("fmt", FORMATS)
def test_name_template_visibility_changes_do_not_cache_or_mutate_source(
    document, tmp_path, fmt
):
    document["design"] = {
        "theme": "classic",
        "templates": {
            "footer": "**NAME's CV** | MONTH_NAME, YEAR | PAGE_NUMBER",
            "top_note": "NAME -- for internal use only -- MONTH_NAME, YEAR",
        },
    }
    document["settings"]["pdf_title"] = "NAME -- MONTH_NAME, YEAR"
    model = model_from(document, tmp_path)
    original = model.model_dump_json()
    visible = render_full_template(model, fmt)
    hidden = None
    for _ in range(3):
        model.cv.hidden_fields[:] = ["name"]
        hidden_source = model.model_dump_json()
        current = render_full_template(model, fmt)
        assert "Example Candidate" not in current
        if hidden is not None:
            assert current == hidden
        hidden = current
        processed = process_model(model, fmt)
        assert processed.design.templates.footer == (
            "**CV** | MONTH_NAME, YEAR | PAGE_NUMBER"
        )
        assert processed.design.templates.top_note == (
            "for internal use only -- MONTH_NAME, YEAR"
        )
        assert processed.settings.pdf_title == "January, 2024"
        assert model.model_dump_json() == hidden_source
        model.cv.hidden_fields.clear()
        assert render_full_template(model, fmt) == visible
        assert model.model_dump_json() == original


@pytest.mark.skipif(
    not shutil.which("pdftotext"),
    reason="Requires Poppler PDF inspection tools",
)
def test_hidden_name_preserves_nested_formatting_and_link_labels_in_pdf(
    document, tmp_path
):
    document["cv"]["hidden_fields"] = ["name", "photo"]
    document["design"] = {
        "theme": "classic",
        "page": {"show_footer": True, "show_top_note": True},
        "templates": {
            "footer": (
                "***NAME** CV* | [NAME](https://example.com/hidden-profile)"
                " | PAGE_NUMBER"
            ),
            "top_note": (
                '[**NAME**](https://example.com/hidden-note "Profile") -- '
                "[NAME's CV](https://example.com/visible-profile_(candidate))"
                " -- MONTH_NAME, YEAR"
            ),
        },
    }
    model = model_from(document, tmp_path)
    original = model.model_dump_json()
    typst_path = generate_typst(model)
    assert typst_path is not None
    typst = typst_path.read_text()
    assert "#emph[CV]" in typst
    assert '#link("https://example.com/visible-profile_(candidate)")[CV]' in typst
    assert "https://example.com/hidden-profile" not in typst
    assert "https://example.com/hidden-note" not in typst
    pdf = generate_pdf(model, typst_path)
    assert pdf is not None
    text = subprocess.run(
        ["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True
    ).stdout
    assert "CV" in text
    assert "January, 2024" in text
    assert "*" not in text
    assert "Example Candidate" not in text
    assert "hidden-profile" not in text
    assert "hidden-note" not in text
    assert "visible-profile" not in text
    assert model.model_dump_json() == original


@pytest.mark.parametrize("fmt", FORMATS)
def test_nested_name_templates_remain_stable_when_toggling_visibility(
    document, tmp_path, fmt
):
    document["design"] = {
        "theme": "classic",
        "templates": {
            "footer": "***NAME** CV* | PAGE_NUMBER",
            "top_note": (
                '[**NAME**](https://example.com/profile "Profile") -- '
                "[NAME's CV](https://example.com/cv) -- MONTH_NAME, YEAR"
            ),
        },
    }
    model = model_from(document, tmp_path)
    original = model.model_dump_json()
    visible = render_full_template(model, fmt)
    shown = process_model(model, fmt)
    assert shown.design.templates.footer == document["design"]["templates"]["footer"]
    assert (
        shown.design.templates.top_note == document["design"]["templates"]["top_note"]
    )
    assert "Example Candidate" in shown.cv._top_note
    hidden = None
    for _ in range(3):
        model.cv.hidden_fields[:] = ["name"]
        before = model.model_dump_json()
        processed = process_model(model, fmt)
        assert processed.design.templates.footer == "*CV* | PAGE_NUMBER"
        assert processed.design.templates.top_note == (
            "[CV](https://example.com/cv) -- MONTH_NAME, YEAR"
        )
        expected_note = "[CV](https://example.com/cv) -- January, 2024"
        if fmt == "typst":
            expected_note = markdown_to_typst(expected_note)
        assert processed.cv._top_note == expected_note
        current = render_full_template(model, fmt)
        if hidden is not None:
            assert current == hidden
        hidden = current
        assert model.model_dump_json() == before
        model.cv.hidden_fields.clear()
        assert render_full_template(model, fmt) == visible
        assert model.model_dump_json() == original


def test_watch_discovery_does_not_collect_hidden_photo_resources(document, tmp_path):
    document["cv"]["photo"] = "unavailable/nested/photo.png"
    document["cv"]["hidden_fields"] = ["photo"]
    source = tmp_path / "cv.yaml"
    source.write_text(json.dumps(document), encoding="utf-8")
    before = source.read_bytes()
    assert collect_input_file_paths(source) == {"input": source}
    model = model_from(document, tmp_path)
    generate_typst(model)
    assert source.read_bytes() == before
    assert not (tmp_path / "unavailable").exists()


def test_all_personal_field_combinations_use_current_visibility(document, tmp_path):
    model = model_from(document, tmp_path)
    markers = {
        "name": "Example Candidate",
        "headline": "Example Headline",
        "location": "Example City",
        "photo": "#grid(",
        "email": "mailto:first@example.com",
        "phone": str(model.cv.phone[0]),
        "website": "https://example.com/first",
        "social_networks": "github.com/example-placeholder",
        "custom_connections": "https://example.com/contact",
    }
    original = model.model_dump_json()
    order = list(model.cv._key_order)
    for mask in range(1 << len(FIELDS)):
        model.cv.hidden_fields[:] = [
            field for i, field in enumerate(FIELDS) if mask & (1 << i)
        ]
        rendered = render_full_template(model, "typst")
        for field, marker in markers.items():
            assert (marker in rendered) == (field not in model.cv.hidden_fields), (
                mask,
                field,
            )
        assert model.cv._key_order == order
    model.cv.hidden_fields.clear()
    assert model.model_dump_json() == original


def test_photo_toggle_refreshes_compiler_output_without_mutating_source(
    document, tmp_path
):
    model = model_from(document, tmp_path)
    original = model.model_dump_json()
    visible = rendered_pngs(model)
    for _ in range(2):
        model.cv.hidden_fields[:] = ["photo"]
        hidden = rendered_pngs(model)
        assert hidden != visible
        model.cv.hidden_fields.clear()
        assert rendered_pngs(model) == visible
    assert model.model_dump_json() == original


def test_hidden_existing_photo_is_not_decoded(document, tmp_path):
    photo = tmp_path / "invalid-image.png"
    photo.write_bytes(b"Not an image; hidden resources must never be decoded.")
    document["cv"].update(photo=str(photo), hidden_fields=["photo"])
    model = model_from(document, tmp_path)
    with patch("shutil.copy", side_effect=AssertionError("Unexpected copy")):
        assert generate_png(model, generate_typst(model))


@pytest.mark.parametrize("marker", ["*", "**", "***", "_", "__", "___"])
@pytest.mark.parametrize(
    "content",
    [
        "CURRENT_DATE",
        "MONTH_NAME",
        "MONTH_ABBREVIATION",
        "MONTH",
        "MONTH_IN_TWO_DIGITS",
        "DAY",
        "DAY_IN_TWO_DIGITS",
        "YEAR",
        "YEAR_IN_TWO_DIGITS",
        "MONTH_NAME, YEAR",
        "NAME_SUFFIX",
        "SURNAME",
    ],
)
@pytest.mark.parametrize("position", ["absent", "before", "after"])
def test_hidden_name_preserves_formatted_date_placeholders_and_identifiers(
    marker, content, position
):
    expected = f"{marker}{content}{marker}"
    template = {
        "absent": expected,
        "before": f"NAME -- {expected}",
        "after": f"{expected} -- NAME",
    }[position]
    assert remove_name_placeholder(template) == expected


@pytest.mark.parametrize("fmt", FORMATS)
def test_hidden_name_preserves_formatted_month_name_when_toggling(
    document, tmp_path, fmt
):
    date_template = "___MONTH_NAME, YEAR___"
    document["settings"].update(
        current_date="2026-01-15", pdf_title=f"{date_template} -- NAME"
    )
    document["design"] = {
        "theme": "classic",
        "page": {"show_footer": True, "show_top_note": True},
        "templates": {
            "footer": date_template,
            "top_note": f"NAME -- {date_template}",
        },
    }
    model = model_from(document, tmp_path)
    original = model.model_dump_json()
    visible = render_full_template(model, fmt)
    expected = "___January, 2026___"
    formatted = markdown_to_typst(expected) if fmt == "typst" else expected
    hidden = None
    for _ in range(3):
        model.cv.hidden_fields[:] = ["name"]
        before = model.model_dump_json()
        processed = process_model(model, fmt)
        assert processed.design.templates.footer == date_template
        assert processed.design.templates.top_note == date_template
        assert formatted in processed.cv._footer
        assert processed.cv._top_note == formatted
        assert processed.settings.pdf_title == expected
        current = render_full_template(model, fmt)
        assert "Example Candidate" not in current
        if hidden is not None:
            assert current == hidden
        hidden = current
        assert model.model_dump_json() == before
        model.cv.hidden_fields.clear()
        assert render_full_template(model, fmt) == visible
        assert model.model_dump_json() == original


@pytest.mark.skipif(
    not shutil.which("pdfinfo") or not shutil.which("pdftotext"),
    reason="Requires Poppler PDF inspection tools",
)
def test_hidden_name_preserves_bold_italic_month_name_in_pdf(document, tmp_path):
    template = "___MONTH_NAME, YEAR___"
    document["cv"]["hidden_fields"] = ["name", "photo"]
    document["settings"].update(current_date="2026-01-15", pdf_title=template)
    document["design"] = {
        "theme": "classic",
        "page": {"show_footer": True, "show_top_note": True},
        "templates": {"footer": template, "top_note": template},
    }
    model = model_from(document, tmp_path)
    original = model.model_dump_json()
    typst_path = generate_typst(model)
    assert typst_path is not None
    typst = typst_path.read_text()
    formatted = markdown_to_typst("___January, 2026___")
    assert "#emph[" in formatted
    assert "#strong[" in formatted
    assert typst.count(formatted) >= 2
    pdf = generate_pdf(model, typst_path)
    assert pdf is not None
    info = subprocess.run(
        ["pdfinfo", str(pdf)], capture_output=True, text=True, check=True
    ).stdout
    text = subprocess.run(
        ["pdftotext", str(pdf), "-"], capture_output=True, text=True, check=True
    ).stdout
    title = next(line for line in info.splitlines() if line.startswith("Title:"))
    assert title.removeprefix("Title:").strip() == "___January, 2026___"
    assert text.count("January, 2026") >= 2
    assert "*" not in text
    assert "_" not in text
    assert "Example Candidate" not in info + text
    assert model.model_dump_json() == original
