import contextlib
import pathlib
import time
from collections.abc import Callable, Mapping
from typing import Literal, Unpack

import jinja2

from rendercv.exception import RenderCVUserError, RenderCVUserValidationError
from rendercv.renderer.html import generate_html
from rendercv.renderer.markdown import generate_markdown
from rendercv.renderer.pdf_png import generate_pdf, generate_png
from rendercv.renderer.typst import generate_typst
from rendercv.schema.rendercv_model_builder import (
    BuildRendercvModelArguments,
    build_rendercv_dictionary_and_model,
    read_yaml_with_validation_errors,
)

from .progress_panel import ProgressPanel

type InputFilePaths = dict[
    Literal["input", "design", "locale", "settings"], pathlib.Path
]


def timed_step[T, **P](
    message: str,
    progress_panel: ProgressPanel,
    func: Callable[P, T],
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """Execute function, measure timing, and update progress panel with result.

    Why:
        Each generation step (Typst, PDF, PNG) returns file paths. This wrapper
        times execution and automatically displays results in progress panel.

    Example:
        ```py
        pdf_path = timed_step(
            "Generated PDF", progress, generate_pdf, rendercv_model, typst_path
        )
        # Progress shows: ✓ 150 ms  Generated PDF: ./cv.pdf
        ```

    Args:
        message: Step description for progress display.
        progress_panel: Progress panel to update.
        func: Function to execute and time.
        args: Positional arguments for func.
        kwargs: Keyword arguments for func.

    Returns:
        Function result.
    """
    start = time.perf_counter()
    result = func(*args, **kwargs)
    end = time.perf_counter()
    timing_ms = f"{(end - start) * 1000:.0f}"

    paths: list[pathlib.Path] = []
    if isinstance(result, pathlib.Path):
        paths = [result]
    elif isinstance(result, list) and result:
        if len(result) > 1:
            message = f"{message}s"
        paths = [p for p in result if isinstance(p, pathlib.Path)]

    if paths:
        progress_panel.update_progress(
            time_took=timing_ms, message=message, paths=paths
        )

    return result


def collect_input_file_paths(
    input_file_path: pathlib.Path,
    design: pathlib.Path | None = None,
    locale: pathlib.Path | None = None,
    settings: pathlib.Path | None = None,
    overrides: dict[str, str] | None = None,
) -> InputFilePaths:
    """Collect all input file paths involved in a render.

    Why:
        A render may involve multiple files: the main YAML, plus overlay
        files for design/locale/settings provided via CLI flags or referenced
        in settings.render_command. Watch mode needs this complete list to
        monitor all of them for changes, and the render pipeline needs the
        resolved paths to read overlay file contents.

    Args:
        input_file_path: Path to the main YAML input file.
        design: CLI-provided design file path.
        locale: CLI-provided locale file path.
        settings: CLI-provided settings file path. Replaces settings in the main YAML.
        overrides: Dotted CLI overrides, applied after dedicated flags.

    Returns:
        Mapping from role ("input", "design", "locale", "settings") to path.
    """
    files: InputFilePaths = {"input": input_file_path}

    if design:
        files["design"] = design
    if locale:
        files["locale"] = locale
    if settings:
        files["settings"] = settings

    # Standalone settings replace the main settings, including their references.
    # Discovery tolerates temporarily missing/invalid files so watch can recover;
    # run_rendercv reports the actual read or validation error on every attempt.
    rc: Mapping = {}
    with contextlib.suppress(OSError, RenderCVUserError, RenderCVUserValidationError):
        source = settings if settings is not None else input_file_path
        document = read_yaml_with_validation_errors(
            source.read_text(encoding="utf-8"),
            "settings_yaml_file" if settings is not None else "main_yaml_file",
        )
        if isinstance(document, Mapping):
            settings_dict = document.get("settings", {})
            if isinstance(settings_dict, Mapping):
                render_command = settings_dict.get("render_command", {})
                if isinstance(render_command, Mapping):
                    rc = render_command

    for role in ("design", "locale"):
        override = (overrides or {}).get(f"settings.render_command.{role}")
        if override is not None:
            files.pop(role, None)
            reference = override
        elif role in files:
            continue
        else:
            reference = rc.get(role)
        if isinstance(reference, str) and reference:
            files[role] = (input_file_path.parent / reference).resolve()

    return files


def run_rendercv(
    input_file_path: pathlib.Path,
    progress: ProgressPanel,
    *,
    input_file_paths: InputFilePaths | None = None,
    **kwargs: Unpack[BuildRendercvModelArguments],
) -> None:
    """Execute complete CV generation pipeline with progress tracking and error handling.

    Args:
        input_file_path: Path to the main YAML input file.
        progress: Progress panel for output display.
        input_file_paths: CLI input files to read afresh for this render.
        kwargs: Optional YAML overlay strings, output paths, and generation flags.
    """
    try:
        main_yaml = input_file_path.read_text(encoding="utf-8")
        if input_file_paths is not None:
            for role, argument in (
                ("settings", "settings_yaml_file"),
                ("design", "design_yaml_file"),
                ("locale", "locale_yaml_file"),
            ):
                if role in input_file_paths:
                    path = input_file_paths[role]
                    content = path.read_text(encoding="utf-8")
                    if not content.strip():
                        message = f"The input file `{path}` is empty!"
                        raise RenderCVUserError(message)
                    kwargs[argument] = content
            # Validate the selected files, not stale references overridden by CLI.
            kwargs["overrides"] = {
                **(kwargs.get("overrides") or {}),
                **{
                    f"settings.render_command.{role}": str(
                        input_file_paths[role].absolute()
                    )
                    for role in ("design", "locale")
                    if role in input_file_paths
                },
            }

        _, rendercv_model = timed_step(
            "Validated the input file",
            progress,
            build_rendercv_dictionary_and_model,
            main_yaml,
            input_file_path=input_file_path,
            **kwargs,
        )
        typst_path = timed_step(
            "Generated Typst",
            progress,
            generate_typst,
            rendercv_model,
        )
        timed_step(
            "Generated PDF",
            progress,
            generate_pdf,
            rendercv_model,
            typst_path,
        )
        timed_step(
            "Generated PNG",
            progress,
            generate_png,
            rendercv_model,
            typst_path,
        )
        md_path = timed_step(
            "Generated Markdown",
            progress,
            generate_markdown,
            rendercv_model,
        )
        timed_step(
            "Generated HTML",
            progress,
            generate_html,
            rendercv_model,
            md_path,
        )
        progress.finish_progress()
    except RenderCVUserError as e:
        progress.print_user_error(e)
    except jinja2.exceptions.TemplateSyntaxError as e:
        progress.print_user_error(
            RenderCVUserError(
                message=(
                    f"There is a problem with the template ({e.filename}) at line"
                    f" {e.lineno}!\n\n{e}"
                )
            )
        )
    except OSError as e:
        progress.print_user_error(RenderCVUserError(message=f"OS Error: {e}"))
    except RenderCVUserValidationError as e:
        progress.print_validation_errors(e.validation_errors)
