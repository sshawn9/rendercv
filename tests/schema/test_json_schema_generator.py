import json

from rendercv import __schema_url__
from rendercv.schema.json_schema_generator import (
    generate_json_schema,
    generate_json_schema_file,
)
from rendercv.schema.sample_generator import create_sample_yaml_input_file


def test_generate_json_schema():
    schema = generate_json_schema()
    assert isinstance(schema, dict)


def test_generate_json_schema_file(tmp_path):
    schema_file_path = tmp_path / "schema.json"
    generate_json_schema_file(schema_file_path)

    assert schema_file_path.exists()

    schema_text = schema_file_path.read_text(encoding="utf-8")
    schema = json.loads(schema_text)

    assert isinstance(schema, dict)


def test_schema_and_new_yaml_use_the_same_fork_schema():

    expected = "https://raw.githubusercontent.com/sshawn9/rendercv/main/schema.json"
    assert __schema_url__ == expected
    assert generate_json_schema()["$id"] == expected
    yaml = create_sample_yaml_input_file(file_path=None)
    assert yaml.splitlines()[0] == f"# yaml-language-server: $schema={expected}"
