import pathlib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Literal

import pydantic

from rendercv.exception import RenderCVUserError
from rendercv.schema.models.cv.cv import photo_validator
from rendercv.schema.models.cv.section import Entry, get_rendercv_sections
from rendercv.schema.models.rendercv_model import RenderCVModel
from rendercv.schema.models.validation_context import ValidationContext

from .connections import compute_connections
from .date import build_date_placeholders, date_object_to_string
from .entry_templates_from_input import render_entry_templates
from .footer_and_top_note import render_footer_template, render_top_note_template
from .markdown_parser import markdown_to_typst
from .name_placeholder import remove_name_placeholder
from .string_processor import (
    apply_string_processors,
    make_keywords_bold,
    substitute_placeholders,
)


def create_rendering_copy(rendercv_model: RenderCVModel) -> RenderCVModel:
    """Apply current personal-field visibility before resources or derived values."""
    result = rendercv_model.model_copy(deep=True)
    hidden = set(result.cv.hidden_fields)
    for field in hidden:
        setattr(result.cv, field, None)
    result.cv._key_order = [key for key in result.cv._key_order if key not in hidden]
    result.cv._rendered_sections = None

    if "name" in hidden:
        result.design.templates.footer = remove_name_placeholder(
            result.design.templates.footer
        )
        result.design.templates.top_note = remove_name_placeholder(
            result.design.templates.top_note
        )
        result.settings.pdf_title = remove_name_placeholder(result.settings.pdf_title)
        if not result.design.templates.footer:
            result.design.page.show_footer = False
        if not result.design.templates.top_note:
            result.design.page.show_top_note = False

    # A previously hidden missing photo may have been unhidden on a live model.
    # Reuse normal photo validation before accessing any visible photo resource.
    if result.cv.photo is not None:
        try:
            result.cv.photo = photo_validator.validate_python(
                result.cv.photo,
                context={
                    "context": ValidationContext(
                        input_file_path=result._input_file_path
                    )
                },
            )
        except pydantic.ValidationError as error:
            message = f"Invalid photo: {error}"
            raise RenderCVUserError(message) from error
    return result


def download_photo_from_url(rendercv_model: RenderCVModel) -> None:
    """Download photo from URL to output directory and update model to local path.

    Why:
        Templates and Typst compiler require cv.photo to be a local pathlib.Path.
        When user provides a URL, this downloads the image before template
        rendering, preserving the local-path invariant for all downstream code.

    Args:
        rendercv_model: CV model whose photo URL will be downloaded in-place.
    """
    if "photo" in rendercv_model.cv.hidden_fields:
        return
    if rendercv_model.cv.photo is None or isinstance(
        rendercv_model.cv.photo, pathlib.Path
    ):
        return

    url_str = str(rendercv_model.cv.photo)

    parsed = urllib.parse.urlparse(url_str)
    filename = pathlib.PurePosixPath(parsed.path).name
    if not filename or "." not in filename:
        filename = "photo.jpg"

    output_dir = rendercv_model.settings.render_command.output_folder
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / filename

    if not destination.exists():
        try:
            with urllib.request.urlopen(url_str, timeout=30) as response:
                destination.write_bytes(response.read())
        except (urllib.error.URLError, OSError) as e:
            raise RenderCVUserError(
                message=f"Failed to download photo from {url_str}: {e}"
            ) from e

    rendercv_model.cv.photo = destination


def process_model(
    rendercv_model: RenderCVModel, file_type: Literal["typst", "markdown"]
) -> RenderCVModel:
    """Pre-process CV model for template rendering with format-specific transformations.

    Why:
        Templates need processed data, not raw model. This applies markdown
        parsing, keyword bolding, connection formatting, date rendering, and
        entry template expansion before templates execute.

    Args:
        rendercv_model: Validated CV model.
        file_type: Target format for format-specific processors.

    Returns:
        Processed model ready for templates.
    """
    rendercv_model = create_rendering_copy(rendercv_model)
    # The source model stays live; only this copy stores the processed view
    # shared by the entry processor and the final templates.
    rendercv_model.cv._rendered_sections = get_rendercv_sections(
        rendercv_model.cv.sections
    )

    string_processors: list[Callable[[str], str]] = [
        lambda string: make_keywords_bold(string, rendercv_model.settings.bold_keywords)
    ]
    if file_type == "typst":
        string_processors.extend([markdown_to_typst])

    rendercv_model.cv._plain_name = (
        "" if "name" in rendercv_model.cv.hidden_fields else rendercv_model.cv.name
    )
    rendercv_model.cv.name = apply_string_processors(
        rendercv_model.cv.name, string_processors
    )
    rendercv_model.cv.headline = apply_string_processors(
        rendercv_model.cv.headline, string_processors
    )
    rendercv_model.cv._connections = compute_connections(rendercv_model, file_type)
    substitute_name = "name" not in rendercv_model.cv.hidden_fields
    rendercv_model.cv._top_note = render_top_note_template(
        rendercv_model.design.templates.top_note,
        locale=rendercv_model.locale,
        current_date=rendercv_model.settings._resolved_current_date,
        name=rendercv_model.cv.name,
        substitute_name=substitute_name,
        single_date_template=rendercv_model.design.templates.single_date,
        string_processors=string_processors,
    )

    rendercv_model.cv._footer = render_footer_template(
        rendercv_model.design.templates.footer,
        locale=rendercv_model.locale,
        current_date=rendercv_model.settings._resolved_current_date,
        name=rendercv_model.cv.name,
        substitute_name=substitute_name,
        single_date_template=rendercv_model.design.templates.single_date,
        string_processors=string_processors,
    )

    pdf_title_placeholders: dict[str, str] = {
        "CURRENT_DATE": date_object_to_string(
            rendercv_model.settings._resolved_current_date,
            locale=rendercv_model.locale,
            single_date_template=rendercv_model.design.templates.single_date,
        ),
        **build_date_placeholders(
            rendercv_model.settings._resolved_current_date, locale=rendercv_model.locale
        ),
    }
    if substitute_name:
        pdf_title_placeholders["NAME"] = rendercv_model.cv._plain_name or ""
    rendercv_model.settings.pdf_title = substitute_placeholders(
        rendercv_model.settings.pdf_title, pdf_title_placeholders
    )

    if rendercv_model.cv.sections is None:
        return rendercv_model

    for section in rendercv_model.cv.rendercv_sections:
        section.title = apply_string_processors(section.title, string_processors)
        show_time_span = (
            section.snake_case_title
            in rendercv_model.design.sections.show_time_spans_in
        )
        for i, entry in enumerate(section.entries):
            processed_entry = render_entry_templates(
                entry,
                templates=rendercv_model.design.templates,
                locale=rendercv_model.locale,
                show_time_span=show_time_span,
                current_date=rendercv_model.settings._resolved_current_date,
            )
            section.entries[i] = process_fields(processed_entry, string_processors)

    return rendercv_model


def process_fields(
    entry: Entry, string_processors: list[Callable[[str], str]]
) -> Entry:
    """Apply string processors to all entry fields except skipped technical fields.

    Why:
        Entry fields need markdown parsing and formatting, but dates, DOIs, and
        URLs must remain unprocessed for correct linking and formatting. Field-
        level processing enables selective transformation.

    Args:
        entry: Entry to process (model or string).
        string_processors: Transformation functions to apply.

    Returns:
        Entry with processed fields.
    """
    skipped = {"start_date", "end_date", "doi", "url", "hidden"}

    if isinstance(entry, str):
        return apply_string_processors(entry, string_processors)

    data = entry.model_dump(exclude_none=True)
    for field, value in data.items():
        if field in skipped or field.startswith("_"):
            continue

        if isinstance(value, str):
            setattr(entry, field, apply_string_processors(value, string_processors))
        elif isinstance(value, list):
            setattr(
                entry,
                field,
                [apply_string_processors(v, string_processors) for v in value],
            )
        else:
            setattr(
                entry, field, apply_string_processors(str(value), string_processors)
            )

    return entry
