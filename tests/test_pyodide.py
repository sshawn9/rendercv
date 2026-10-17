import base64
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

from rendercv.renderer.templater.templater import render_full_template
from rendercv.schema.rendercv_model_builder import build_rendercv_dictionary_and_model

PROJECT_ROOT = pathlib.Path(__file__).parent.parent


@pytest.fixture
def js_runtime(tmp_path: pathlib.Path) -> str:
    """Provide a JS runtime with pyodide installed in tmp.

    Why:
        The Pyodide test needs a JS runtime with the pyodide npm package.
        Node.js is preferred, but if unavailable, bun is used (or installed
        on the fly since it's a single ~13MB download). Pyodide is installed
        into tmp_path so node_modules never touches the repo.

    Returns:
        Absolute path to the JS runtime binary.
    """
    node = shutil.which("node")
    if node is not None:
        # On Windows, npm is a .cmd batch script that requires shell=True
        shell = sys.platform == "win32"
        subprocess.run(
            ["npm", "init", "-y"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            timeout=120,
            shell=shell,
        )
        subprocess.run(
            ["npm", "install", "pyodide"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            timeout=300,
            shell=shell,
        )
        return node

    bun = shutil.which("bun")
    if bun is None:
        # Install bun into tmp
        bun_dir = tmp_path / "bun"
        subprocess.run(
            [
                "bash",
                "-c",
                f"curl -fsSL https://bun.sh/install | BUN_INSTALL={bun_dir} bash",
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        bun = str(bun_dir / "bin" / "bun")

    subprocess.run(
        [bun, "add", "pyodide"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        timeout=120,
    )
    return bun


def test_rendercv_installs_and_renders_visibility_in_pyodide(
    tmp_path: pathlib.Path, js_runtime: str
) -> None:
    # Build the wheel into tmp
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path / "dist")],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        timeout=60,
    )
    wheel = next((tmp_path / "dist").glob("rendercv-*-py3-none-any.whl"))

    # Use forward slashes so the path works on Windows too
    wheel_posix_path = wheel.resolve().as_posix()

    # Feed the identical YAML to native Python and the wheel inside Pyodide.
    source = """cv:
  name: Visibility
  phone: ["+14155552671", "+442071838750"]
  email: ["a@example.com", "b@example.com"]
  website: ["https://a.example.com/path/", "https://b.example.com/"]
  custom_connections:
    - fontawesome_icon: phone
      placeholder: Contact
  sections:
    Work:
      entries:
        - name: Visible
          start_date: 2021-02
          end_date: 2022-02
          highlights:
            - "**Already bold**"
            - Parent highlight
              - Child highlight
        - name: Secret
          hidden: true
    Archived:
      hidden: true
      entries:
        - bullet: Secret section
    Summary:
      - Plain text
      - text: Secret text
        hidden: true
    Education:
      - institution: Example University
        area: CS
        degree: UniqueDegree
design:
  theme: harvard
  page:
    top_margin: .5cm
  sections:
    show_time_spans_in: [work]
  templates:
    time_span: "HOW_MANY_YEARS YEARS HOW_MANY_MONTHS MONTHS"
    normal_entry:
      date_and_location_column: "**DATE**"
settings:
  current_date: 2026-10-15
  bold_keywords: [Visible, Already bold]
"""
    _, model = build_rendercv_dictionary_and_model(source)
    expected = {
        "typst": render_full_template(model, "typst"),
        "markdown": render_full_template(model, "markdown"),
    }
    assert all("Secret" not in output for output in expected.values())
    assert expected["typst"].count("UniqueDegree") == 1
    assert "#strong[Visible]" in expected["typst"]
    assert "#strong[Already bold]" in expected["typst"]
    assert "#strong[1 year 1 month]" in expected["typst"]
    assert "      - Child highlight" in expected["typst"]
    assert "- Contact" in expected["markdown"]
    assert expected["markdown"].count("- Phone:") == 2
    assert "[a@example.com](mailto:a@example.com)" in expected["markdown"]
    assert "[b@example.com](mailto:b@example.com)" in expected["markdown"]
    assert "[a.example.com/path](https://a.example.com/path/)" in expected["markdown"]
    hidden_data, _ = build_rendercv_dictionary_and_model(source)
    hidden_data["cv"].update(
        name="Example Candidate",
        phone=["+12025550123", "+12025550124"],
        photo="https://example.invalid/unavailable.png",
        hidden_fields=[
            "name",
            "photo",
            "phone",
            "email",
            "website",
            "custom_connections",
        ],
    )
    hidden_data["design"]["templates"].update(
        footer="***NAME** CV* | [NAME](https://example.com/hidden-profile) | PAGE_NUMBER",
        top_note="[NAME's CV](https://example.com/cv) -- ___MONTH_NAME, YEAR___",
    )
    hidden_data["design"]["page"].update(show_footer=True, show_top_note=True)
    hidden_source = json.dumps(hidden_data)
    _, hidden_model = build_rendercv_dictionary_and_model(hidden_source)
    hidden_before = hidden_model.model_dump_json()
    hidden_expected = {
        "typst": render_full_template(hidden_model, "typst"),
        "markdown": render_full_template(hidden_model, "markdown"),
    }
    assert "#emph[CV]" in hidden_expected["typst"]
    assert '#link("https://example.com/cv")[CV]' in hidden_expected["typst"]
    assert "hidden-profile" not in hidden_expected["typst"]
    assert "#strong[#emph[October, 2026]]" in hidden_expected["typst"]
    assert hidden_model.model_dump_json() == hidden_before
    fixture = base64.b64encode(
        json.dumps(
            {
                "source": source,
                "expected": expected,
                "hidden_source": hidden_source,
                "hidden_expected": hidden_expected,
            }
        ).encode()
    ).decode()

    script = tmp_path / "test.mjs"
    script.write_text(f"""\
import fs from "node:fs";
import {{ loadPyodide }} from "pyodide";

async function main() {{
    const pyodide = await loadPyodide();

    // Copy wheel into Pyodide's virtual filesystem to avoid file:// URL
    // issues on Windows
    const wheelData = fs.readFileSync("{wheel_posix_path}");
    pyodide.FS.writeFile("/tmp/{wheel.name}", wheelData);

    await pyodide.loadPackage("micropip");

    await pyodide.runPythonAsync(`
import micropip

# Pre-install email-validator because micropip may not resolve
# pydantic[email] extras notation correctly
await micropip.install("email-validator")

# Install rendercv from Pyodide's virtual filesystem
await micropip.install("emfs:/tmp/{wheel.name}")

# Verify visibility and native/WASM parity, beyond a successful import.
import base64, json
from rendercv.schema.rendercv_model_builder import build_rendercv_dictionary_and_model
from rendercv.renderer.templater.templater import render_full_template
from rendercv.exception import RenderCVUserError
assert str(RenderCVUserError(message="Example error")) == "Example error"
case = json.loads(base64.b64decode("{fixture}"))
_, model = build_rendercv_dictionary_and_model(case["source"])
before = model.cv.model_dump_json()
for fmt, expected in case["expected"].items():
    assert render_full_template(model, fmt) == expected, fmt
assert model.cv.model_dump_json() == before
assert model.cv.sections["Archived"].hidden is True
assert model.cv.sections["Summary"][1].hidden is True

# Personal-field visibility uses the same YAML protocol in native Python and WASM.
from unittest.mock import patch
for photo_value in ["https://example.invalid/unavailable.png", "images/missing.png"]:
    hidden_input = json.loads(case["hidden_source"])
    hidden_input["cv"]["photo"] = photo_value
    _, hidden_model = build_rendercv_dictionary_and_model(json.dumps(hidden_input))
    hidden_before = hidden_model.model_dump_json()
    with patch("urllib.request.urlopen", side_effect=AssertionError("Hidden photo accessed")):
        for fmt, expected in case["hidden_expected"].items():
            assert render_full_template(hidden_model, fmt) == expected, fmt
        hidden_model.cv.hidden_fields.remove("name")
        assert "Example Candidate" in render_full_template(hidden_model, "typst")
        hidden_model.cv.hidden_fields.insert(0, "name")
        assert render_full_template(hidden_model, "typst") == case["hidden_expected"]["typst"]
    assert hidden_model.model_dump_json() == hidden_before

# Standalone Typst export must work without the native Typst compiler package.
from pathlib import Path
from rendercv.renderer.typst import generate_typst
photo = Path("/tmp/avatar.jpg")
photo.write_bytes(b"photo fixture")
export_model = model.model_copy(deep=True)
export_model.cv.photo = photo
export_model.settings.render_command.typst_path = Path("/tmp/standalone/cv.typ")
typst_path = generate_typst(export_model)
assert typst_path is not None
assert (typst_path.parent / photo.name).read_bytes() == photo.read_bytes()
assert model.cv.model_dump_json() == before
    `);
}}

main().catch(err => {{
    console.error(err.message);
    process.exit(1);
}});
""")

    # Run test
    result = subprocess.run(
        [js_runtime, str(script)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, f"Pyodide install failed:\n{result.stderr}"
