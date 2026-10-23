from importlib import import_module
from pathlib import Path

import pandas as pd
import pytest

initializer = import_module("etl.initializer")
runner = import_module("etl.runner")


@pytest.mark.parametrize("configured", [False, True])
def test_create_task_preserves_configuration(tmp_path: Path, configured: bool) -> None:
    inputs = [tmp_path / "input.csv"]
    output = tmp_path / "output.csv"

    def transform(frame: pd.DataFrame) -> pd.DataFrame:
        return frame

    def inspect(frame: pd.DataFrame) -> None:
        assert "code" in frame

    task = initializer.create_task(inputs=inputs, output=output, transform=transform)
    if configured:
        task = initializer.create_task(
            inputs=inputs, output=output, transform=transform,
            validate=inspect, report=inspect, overwrite=True,
        )
    assert isinstance(task, runner.TaskDefinition)
    assert task.inputs == inputs
    assert task.output == output
    assert task.transform is transform
    assert task.validate is (inspect if configured else None)
    assert task.report is (inspect if configured else None)
    assert task.overwrite is configured


@pytest.mark.parametrize(
    "scenario", ["defaults", "callbacks", "invalid", "existing", "overwrite", "missing_input"]
)
def test_initialize_publishes_task_and_returns_status(tmp_path: Path, scenario: str) -> None:
    source = tmp_path / "input.csv"
    output = tmp_path / "output.csv"
    reported = []
    source.write_text("code\n01260\n", encoding="utf-8")
    if scenario in ("existing", "overwrite"):
        output.write_text("existing", encoding="utf-8")

    def transform(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.rename(columns={"code": "identifier"})

    def validate(frame: pd.DataFrame) -> None:
        if scenario == "invalid":
            raise import_module("etl.errors").EtlValidationError("Rejected identifier")
        assert frame.identifier.tolist() == ["01260"]

    def report(frame: pd.DataFrame) -> None:
        published = pd.read_csv(output, dtype="string")
        assert published.identifier.tolist() == frame.identifier.tolist()
        reported.extend(frame.identifier.tolist())

    success = scenario in ("defaults", "callbacks", "overwrite")
    result = initializer.initialize(
        inputs=[] if scenario == "missing_input" else [source],
        output=output,
        transform=transform,
        validate=None if scenario == "defaults" else validate,
        report=None if scenario == "defaults" else report,
        overwrite=scenario == "overwrite",
    )
    assert result is success
    assert reported == (["01260"] if scenario in ("callbacks", "overwrite") else [])
    if success:
        actual = pd.read_csv(output, dtype="string")
        assert actual.identifier.tolist() == ["01260"]
    elif scenario == "existing":
        assert output.read_text(encoding="utf-8") == "existing"
    else:
        assert not output.exists()
