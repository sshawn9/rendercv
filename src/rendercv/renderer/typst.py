import pathlib
import shutil

from rendercv.schema.models.rendercv_model import RenderCVModel

from .path_resolver import resolve_rendercv_file_path
from .templater.templater import render_full_template


def generate_typst(rendercv_model: RenderCVModel) -> pathlib.Path | None:
    """Generate Typst source file from CV model via Jinja2 templates.

    Why:
        Typst is the intermediate format before PDF/PNG compilation. Templates
        convert validated model data to Typst markup with proper formatting,
        fonts, and styling from design options.

    Args:
        rendercv_model: Validated CV model with content and design.

    Returns:
        Path to generated Typst file, or None if generation disabled.
    """
    if rendercv_model.settings.render_command.dont_generate_typst:
        return None
    typst_path = resolve_rendercv_file_path(
        rendercv_model, rendercv_model.settings.render_command.typst_path
    )
    typst_contents = render_full_template(rendercv_model, "typst")
    copy_photo_next_to_typst_file(rendercv_model, typst_path)
    typst_path.write_text(typst_contents, encoding="utf-8")
    return typst_path


def copy_photo_next_to_typst_file(
    rendercv_model: RenderCVModel, typst_path: pathlib.Path
) -> None:
    """Copy CV photo to Typst file directory for export and compilation.

    Why:
        Typst compiler resolves image paths relative to source file location.
        Copying photo ensures compilation succeeds regardless of original
        photo location.

    Args:
        rendercv_model: CV model containing photo path.
        typst_path: Path to Typst source file.
    """
    photo_path = rendercv_model.cv.photo
    if isinstance(photo_path, pathlib.Path):
        copy_to = typst_path.parent / photo_path.name
        if photo_path.resolve() != copy_to.resolve():
            shutil.copy(photo_path, copy_to)
