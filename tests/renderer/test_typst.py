import shutil

import pytest

from rendercv.renderer.pdf_png import get_typst_compiler
from rendercv.renderer.templater.templater import render_full_template
from rendercv.renderer.typst import generate_typst
from rendercv.schema.models.design.built_in_design import available_themes
from rendercv.schema.models.rendercv_model import RenderCVModel
from rendercv.schema.rendercv_model_builder import build_rendercv_dictionary_and_model


@pytest.mark.parametrize("theme", available_themes)
@pytest.mark.parametrize("cv_variant", ["minimal", "full"])
def test_generate_typst(
    compare_file_with_reference,
    theme: str,
    cv_variant: str,
    request: pytest.FixtureRequest,
):
    base_model = request.getfixturevalue(f"{cv_variant}_rendercv_model")

    model = RenderCVModel(
        cv=base_model.cv,
        design={"theme": theme},
        locale=base_model.locale,
        settings=base_model.settings,
    )

    def generate_file(output_path):
        model.settings.render_command.typst_path = output_path
        generate_typst(model)

    reference_filename = f"{theme}_{cv_variant}.typ"
    assert compare_file_with_reference(generate_file, reference_filename)


@pytest.mark.parametrize("theme", available_themes)
def test_education_degree_is_rendered_once(theme):

    model = RenderCVModel.model_validate(
        {
            "cv": {
                "sections": {
                    "education": [
                        {
                            "institution": "Example University",
                            "area": "CS",
                            "degree": "UniqueDegree",
                        }
                    ]
                }
            },
            "design": {"theme": theme},
        }
    )
    assert render_full_template(model, "typst").count("UniqueDegree") == 1


def test_nested_highlights_retain_levels_in_rendered_typst():

    _, model = build_rendercv_dictionary_and_model("""cv:
  sections:
    experience:
      - company: Example Company
        position: Engineer
        highlights:
          - Parent highlight
            - Child highlight
            - Another child highlight
""")
    output = render_full_template(model, "typst")
    assert [
        line
        for line in output.splitlines()
        if "highlight" in line and line.lstrip().startswith("- ")
    ] == [
        "    - Parent highlight",
        "      - Child highlight",
        "      - Another child highlight",
    ]


@pytest.mark.parametrize("already_in_output", [False, True])
def test_typst_only_export_includes_photo_and_compiles(
    tmp_path, testdata_dir, already_in_output
):
    source_dir = tmp_path / "images"
    source_dir.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    photo = (output if already_in_output else source_dir) / "photo.jpg"
    shutil.copyfile(testdata_dir.parent / "profile_picture.jpg", photo)
    model = RenderCVModel.model_validate(
        {
            "cv": {"name": "Photo export", "photo": str(photo)},
            "settings": {
                "render_command": {
                    "typst_path": str(output / "cv.typ"),
                    "dont_generate_pdf": True,
                    "dont_generate_png": True,
                }
            },
        }
    )
    typst_path = generate_typst(model)
    assert typst_path is not None
    assert (output / "photo.jpg").read_bytes() == photo.read_bytes()
    assert not list(output.glob("*.pdf"))
    compiled = get_typst_compiler(None, output).compile(input=typst_path, format="pdf")
    assert isinstance(compiled, bytes)
    assert compiled.startswith(b"%PDF")


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("english", "MSc in Physics"),
        ("spanish", "MSc en Physics"),
        ("mandarin_chinese", "Physics MSc"),
    ],
)
@pytest.mark.parametrize("degree", [None, "MSc"])
def test_sb2nov_education_uses_locale_phrase_without_orphan_markup(
    language, expected, degree
):
    model = RenderCVModel.model_validate(
        {
            "cv": {
                "name": "Locale probe",
                "sections": {
                    "education": [
                        {
                            "institution": "University",
                            "area": "Physics",
                            "degree": degree,
                        }
                    ]
                },
            },
            "design": {"theme": "sb2nov"},
            "locale": {"language": language},
        }
    )
    rendered = render_full_template(model, "typst")
    assert (expected if degree else "Physics") in rendered
    assert "#sym.ast.basic" not in rendered
    assert "#emph[in]" not in rendered
