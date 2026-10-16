import pickle

import pytest

from rendercv.exception import (
    RenderCVInternalError,
    RenderCVUserError,
    RenderCVUserValidationError,
    RenderCVValidationError,
)


@pytest.mark.parametrize("error_type", [RenderCVUserError, RenderCVInternalError])
@pytest.mark.parametrize("keyword", [False, True])
def test_exception_message_survives_construction_and_pickling(error_type, keyword):
    error = (
        error_type(message="Example error") if keyword else error_type("Example error")
    )
    assert str(error) == "Example error"
    assert error.args == ("Example error",)
    restored = pickle.loads(pickle.dumps(error))
    assert str(restored) == str(error)
    assert restored.message == error.message


def test_validation_exception_keeps_diagnostics_when_raised_with_keywords():
    diagnostics = [
        RenderCVValidationError(
            schema_location=("cv", "name"),
            yaml_location=None,
            yaml_source="main_yaml_file",
            message="Expected text",
            input="42",
        )
    ]
    error = RenderCVUserValidationError(validation_errors=diagnostics)
    assert "Expected text" in str(error)
    assert error.args == (diagnostics,)
    restored = pickle.loads(pickle.dumps(error))
    assert restored.validation_errors == diagnostics


def test_user_error_without_message_stays_empty():
    error = RenderCVUserError()
    assert str(error) == ""
    assert error.args == ()
