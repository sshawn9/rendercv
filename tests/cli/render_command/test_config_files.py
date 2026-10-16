"""Exercise file-based configuration through the real render command."""

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from rendercv.cli.app import app
from rendercv.cli.render_command import render_command as command
from rendercv.cli.render_command.run_rendercv import collect_input_file_paths


@pytest.fixture
def config_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cv_dir = tmp_path / "input"
    config_dir = tmp_path / "config"
    cv_dir.mkdir()
    config_dir.mkdir()
    cv = cv_dir / "cv.yaml"
    cv.write_text("cv:\n  name: John Doe\n", encoding="utf-8")
    settings = config_dir / "settings.yaml"
    settings.write_text(
        "settings:\n  render_command:\n"
        "    design: design.yaml\n    locale: locale.yaml\n",
        encoding="utf-8",
    )
    (cv_dir / "design.yaml").write_text(
        "design:\n  theme: moderncv\n", encoding="utf-8"
    )
    (cv_dir / "locale.yaml").write_text(
        "locale:\n  language: turkish\n", encoding="utf-8"
    )
    return cv, settings


def render(cv, *arguments):
    return CliRunner().invoke(
        app,
        ["render", str(cv), "--dont-generate-pdf", "--dont-generate-png", *arguments],
    )


def typst_output(cv):
    return (cv.parent / "rendercv_output" / "John_Doe_CV.typ").read_text(
        encoding="utf-8"
    )


def test_standalone_settings_loads_both_references_relative_to_cv(config_files):
    cv, settings = config_files
    # The main file, settings file, and working directory are all different.
    result = render(cv.relative_to(Path.cwd()), "--settings", str(settings))

    assert result.exit_code == 0, result.output
    output = typst_output(cv)
    assert "Fontin" in output
    assert 'locale-catalog-language: "tr"' in output


@pytest.mark.parametrize("reference", ["design", "locale"])
def test_cli_file_replaces_even_a_missing_settings_reference(config_files, reference):
    cv, settings = config_files
    settings.write_text(
        f"settings:\n  render_command:\n    {reference}: missing.yaml\n",
        encoding="utf-8",
    )
    cli_file = Path(f"cli_{reference}.yaml")
    cli_file.write_text((cv.parent / f"{reference}.yaml").read_text(), encoding="utf-8")
    flag = "--design" if reference == "design" else "--locale-catalog"

    result = render(cv, "--settings", str(settings), flag, str(cli_file))

    assert result.exit_code == 0, result.output
    expected = "Fontin" if reference == "design" else 'locale-catalog-language: "tr"'
    assert expected in typst_output(cv)


@pytest.mark.parametrize(
    "replacement", ["settings: {}\n", "settings:\n  current_date: 2035-01-15\n"]
)
def test_standalone_settings_replaces_main_settings(config_files, replacement):
    cv, settings = config_files
    cv.write_text(
        "cv:\n  name: John Doe\nsettings:\n  render_command:\n"
        "    design: missing.yaml\n    locale: missing.yaml\n",
        encoding="utf-8",
    )
    settings.write_text(replacement, encoding="utf-8")

    result = render(cv, "--settings", str(settings))

    assert result.exit_code == 0, result.output
    assert "Fontin" not in typst_output(cv)
    assert 'locale-catalog-language: "en"' in typst_output(cv)


@pytest.mark.parametrize(
    ("extra_arguments", "expect_fontin"),
    [([], True), (["--design.theme", "classic"], False)],
)
def test_dotted_path_override_selects_the_file_and_field_overrides_apply_last(
    config_files,
    extra_arguments,
    expect_fontin,
):
    cv, settings = config_files
    settings.write_text(
        "settings:\n  render_command:\n    design: missing.yaml\n",
        encoding="utf-8",
    )
    unused = Path("unused.yaml")
    unused.write_text("design:\n  theme: sb2nov\n", encoding="utf-8")
    result = render(
        cv,
        "--settings",
        str(settings),
        "--design",
        str(unused),
        "--settings.render_command.design",
        "design.yaml",
        *extra_arguments,
    )

    assert result.exit_code == 0, result.output
    assert ("Fontin" in typst_output(cv)) is expect_fontin
    files = collect_input_file_paths(
        cv,
        design=unused,
        settings=settings,
        overrides={"settings.render_command.design": "design.yaml"},
    )
    assert files["design"] == cv.parent / "design.yaml"


def test_watch_reloads_contents_and_switches_referenced_files(
    config_files, monkeypatch
):
    cv, settings = config_files

    def watch(file_paths, callback):
        assert callable(file_paths)
        assert cv.parent / "design.yaml" in file_paths()
        callback()
        assert "Fontin" in typst_output(cv)

        (cv.parent / "design.yaml").write_text(
            "design:\n  theme: classic\n", encoding="utf-8"
        )
        (cv.parent / "locale.yaml").write_text(
            "locale:\n  language: english\n", encoding="utf-8"
        )
        callback()
        assert "Fontin" not in typst_output(cv)
        assert 'locale-catalog-language: "en"' in typst_output(cv)

        new_file = settings.parent / "new.yaml"
        new_file.write_text("design:\n  theme: moderncv\n", encoding="utf-8")
        settings.write_text(
            "settings:\n  render_command:\n    design: ../config/new.yaml\n",
            encoding="utf-8",
        )
        assert new_file in file_paths()
        assert cv.parent / "design.yaml" not in file_paths()
        assert cv.parent / "locale.yaml" not in file_paths()
        callback()
        assert "Fontin" in typst_output(cv)
        new_file.write_text("design:\n  theme: classic\n", encoding="utf-8")
        callback()
        assert "Fontin" not in typst_output(cv)

    monkeypatch.setattr(command, "run_function_if_files_change", watch)
    result = render(cv, "--settings", str(settings), "--watch")
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    "bad_config",
    [
        None,
        "settings: [\n",
        "",
        "locale: {}\n",
        "settings: null\n",
        "settings: []\n",
        "settings:\n  render_command: null\n",
        "[]\n",
        "incomplete\n",
    ],
)
def test_watch_recovers_after_missing_or_invalid_settings(
    config_files, monkeypatch, bad_config
):
    cv, settings = config_files
    if bad_config is None:
        settings.unlink()
    else:
        settings.write_text(bad_config, encoding="utf-8")

    def watch(file_paths, callback):
        assert set(file_paths()) == {cv, settings}
        with pytest.raises(typer.Exit) as error:
            callback()
        assert error.value.exit_code == 1
        settings.write_text(
            "settings:\n  render_command:\n    design: design.yaml\n",
            encoding="utf-8",
        )
        callback()
        assert "Fontin" in typst_output(cv)

    monkeypatch.setattr(command, "run_function_if_files_change", watch)
    result = render(cv, "--settings", str(settings), "--watch")
    assert result.exit_code == 0, result.output


def test_invalid_settings_reports_the_overlay_source(config_files):
    cv, settings = config_files
    settings.write_text("settings: [\n", encoding="utf-8")
    result = render(cv, "--settings", str(settings))
    assert result.exit_code == 1
    assert "settings" in result.output
    assert "valid YAML" in result.output


@pytest.mark.parametrize("role", ["design", "locale"])
@pytest.mark.parametrize("bad_content", [None, "", "invalid: [\n"])
def test_watch_recovers_after_referenced_file_errors(
    config_files, monkeypatch, role, bad_content
):
    cv, settings = config_files
    path = cv.parent / f"{role}.yaml"
    good_content = path.read_text(encoding="utf-8")
    if bad_content is None:
        path.unlink()
    else:
        path.write_text(bad_content, encoding="utf-8")

    def watch(file_paths, callback):
        assert path in file_paths()
        with pytest.raises(typer.Exit) as error:
            callback()
        assert error.value.exit_code == 1
        path.write_text(good_content, encoding="utf-8")
        callback()
        assert "Fontin" in typst_output(cv)
        assert 'locale-catalog-language: "tr"' in typst_output(cv)

    monkeypatch.setattr(command, "run_function_if_files_change", watch)
    result = render(cv, "--settings", str(settings), "--watch")
    assert result.exit_code == 0, result.output


def test_watch_refreshes_references_in_the_main_cv(config_files, monkeypatch):
    cv, _ = config_files
    original = cv.read_text(encoding="utf-8")
    cv.write_text(
        original + "settings:\n  render_command:\n    design: design.yaml\n",
        encoding="utf-8",
    )

    def watch(file_paths, callback):
        callback()
        assert "Fontin" in typst_output(cv)
        cv.write_text(original, encoding="utf-8")
        assert file_paths() == [cv]
        callback()
        assert "Fontin" not in typst_output(cv)

    monkeypatch.setattr(command, "run_function_if_files_change", watch)
    result = render(cv, "--watch")
    assert result.exit_code == 0, result.output
