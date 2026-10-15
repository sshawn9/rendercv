from typing import Annotated, Any

import pydantic

from .bases.entry import BaseEntry


class TextEntry(BaseEntry):
    """An explicit text entry carrying visibility; plain strings remain valid."""

    model_config = pydantic.ConfigDict(extra="forbid")

    text: str = pydantic.Field(
        description="The text of this entry, with Markdown support."
    )


def validate_text_entry(value: Any) -> str | TextEntry:
    # Dispatch before union validation to keep errors at the actual YAML path,
    # without synthetic `str` / `TextEntry` union branches.
    return value if isinstance(value, str) else TextEntry.model_validate(value)


type TextEntryInput = Annotated[
    str | TextEntry,
    pydantic.PlainValidator(
        validate_text_entry, json_schema_input_type=str | TextEntry
    ),
]
