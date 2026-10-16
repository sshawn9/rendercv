import pytest

from rendercv.renderer.html import generate_html
from rendercv.renderer.markdown import generate_markdown
from rendercv.renderer.templater.templater import render_full_template
from rendercv.schema.models.rendercv_model import RenderCVModel


@pytest.mark.parametrize("cv_variant", ["minimal", "full"])
def test_generate_markdown(
    compare_file_with_reference,
    cv_variant: str,
    request: pytest.FixtureRequest,
):
    base_model = request.getfixturevalue(f"{cv_variant}_rendercv_model")

    model = RenderCVModel(
        cv=base_model.cv,
        locale=base_model.locale,
        settings=base_model.settings,
    )

    def generate_file(output_path):
        model.settings.render_command.markdown_path = output_path
        generate_markdown(model)

    reference_filename = f"{cv_variant}.md"
    assert compare_file_with_reference(generate_file, reference_filename)


def test_multiple_contacts_render_individual_links_in_markdown_and_html(tmp_path):
    model = RenderCVModel.model_validate(
        {
            "cv": {
                "name": "Example",
                "phone": ["+14155552671", "+442071838750"],
                "email": ["a@example.com", "b@example.com"],
                "website": ["https://a.example.com/path/", "http://b.example.com/"],
                "custom_connections": [
                    {
                        "fontawesome_icon": "link",
                        "placeholder": "Portfolio",
                        "url": "https://portfolio.example.com/",
                    },
                    {
                        "fontawesome_icon": "phone",
                        "placeholder": "Contact by appointment",
                    },
                ],
            }
        }
    )
    model.settings.render_command.markdown_path = tmp_path / "cv.md"
    model.settings.render_command.html_path = tmp_path / "cv.html"
    markdown_path = generate_markdown(model)
    assert markdown_path is not None
    markdown = markdown_path.read_text()
    assert "- Phone: +1 415 555 2671" in markdown
    assert "- Phone: +44 20 7183 8750" in markdown
    for email in ["a@example.com", "b@example.com"]:
        assert f"- Email: [{email}](mailto:{email})" in markdown
    assert "- Website: [a.example.com/path](https://a.example.com/path/)" in markdown
    assert "- Website: [b.example.com](http://b.example.com/)" in markdown
    assert "- [Portfolio](https://portfolio.example.com/)" in markdown
    assert "- Contact by appointment" in markdown
    assert "HttpUrl(" not in markdown
    html_path = generate_html(model, markdown_path)
    assert html_path is not None
    html = html_path.read_text()
    for url in [
        "mailto:a@example.com",
        "mailto:b@example.com",
        "https://a.example.com/path/",
        "http://b.example.com/",
        "https://portfolio.example.com/",
    ]:
        assert f'href="{url}"' in html
    assert "Contact by appointment" in html


@pytest.mark.parametrize("as_lists", [False, True])
def test_scalar_and_single_item_contacts_keep_existing_header_format(as_lists):
    fields = {
        "phone": "+14155552671",
        "email": "a@example.com",
        "website": "https://a.example.com/",
    }
    if as_lists:
        fields = {key: [value] for key, value in fields.items()}
    output = render_full_template(
        RenderCVModel.model_validate({"cv": {"name": "Example", **fields}}), "markdown"
    )
    assert [line for line in output.splitlines() if line.startswith("- ")] == [
        "- Phone: +1 415 555 2671",
        "- Email: [a@example.com](mailto:a@example.com)",
        "- Website: [a.example.com](https://a.example.com/)",
    ]


@pytest.mark.parametrize("value", [None, []])
def test_empty_contact_fields_do_not_emit_rows_or_fail(value):
    model = RenderCVModel.model_validate(
        {
            "cv": {
                "name": "Example",
                "phone": value,
                "email": value,
                "website": value,
                "custom_connections": value,
            }
        }
    )
    output = render_full_template(model, "markdown")
    assert "Example" in output
    assert not any(line.startswith("- ") for line in output.splitlines())
