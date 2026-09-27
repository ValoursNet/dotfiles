"""Run with python3 -B test_api_key.py; uses dummy keys and no external services."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import judge


def test_api_key():
    with TemporaryDirectory() as directory:
        key_file = Path(directory) / ".typesafe_api_key"
        for environment, contents, expected in [
            ({"TYPESAFE_API_KEY": "test-env"}, None, "test-env"),
            ({"TYPESAFE_API_KEY": "test-env"}, "test-file", "test-env"),
            ({}, "  test-file\n", "test-file"),
            ({}, " \n", None),
            ({}, None, None),
        ]:
            if contents is None:
                key_file.unlink(missing_ok=True)
            else:
                key_file.write_text(contents)
            with patch.dict(os.environ, environment, clear=True), \
                 patch.object(judge, "KEY_FILE", str(key_file)), \
                 patch.object(judge, "_KEY", None), \
                 patch.object(judge.subprocess, "run", side_effect=AssertionError("External credential lookup")):
                if expected is not None:
                    assert judge.api_key() == expected
                else:
                    try:
                        judge.api_key()
                    except SystemExit as error:
                        assert "no TYPESAFE_API_KEY" in str(error)
                    else:
                        raise AssertionError("Missing key must fail")


if __name__ == "__main__":
    test_api_key()
    print("API key checks passed")
