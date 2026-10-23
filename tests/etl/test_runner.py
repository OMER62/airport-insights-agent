from importlib import import_module
from pathlib import Path
from typing import List

import pandas as pd
import pytest
from test_flight_activity import ROW

transform = import_module("etl.tasks.t1_flight_activity").transform
validate_activity = import_module("etl.tasks.t1_flight_activity").validate_activity
run_csv = import_module("etl.runner").run_csv


@pytest.mark.parametrize("values", [["01260"], ["01260", "NA"]])
def test_run_csv_preserves_text_and_combines_files(tmp_path: Path, values: List[str]) -> None:
    inputs = []
    output = tmp_path / "output.csv"
    for index, value in enumerate(values):
        source = tmp_path / f"input-{index}.csv"
        source.write_text(f"code\n{value}\n", encoding="utf-8")
        inputs.append(source)
    result = run_csv(inputs=inputs, output=output, transform=lambda frame: frame)
    assert result is not None
    actual = pd.read_csv(output, dtype="string", keep_default_na=False)
    assert actual.code.tolist() == values


@pytest.mark.parametrize(
    "scenario",
    [
        "existing",
        "same_input",
        "no_inputs",
        "missing_file",
        "invalid_numeric",
        "duplicate_across_files",
        "missing_column_in_one_file",
        "overwrite",
        "write_failure",
    ],
)
def test_run_csv_protects_inputs_and_existing_output(
    tmp_path: Path, scenario: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    source = tmp_path / "input.csv"
    second = tmp_path / "second.csv"
    output = tmp_path / "output.csv"
    inputs = [source]
    overwrite = scenario != "existing"
    row = {**ROW, "PASSENGERS": "bad"} if scenario == "invalid_numeric" else ROW
    pd.DataFrame([row]).to_csv(path_or_buf=source, index=False)
    original = source.read_bytes()
    output.write_text("existing", encoding="utf-8")
    if scenario == "same_input":
        output = source
    if scenario == "no_inputs":
        inputs = []
    if scenario == "missing_file":
        inputs = [second]
    if scenario == "duplicate_across_files":
        inputs.append(source)
    if scenario == "missing_column_in_one_file":
        pd.DataFrame([{"YEAR": "2025"}]).to_csv(path_or_buf=second, index=False)
        inputs.append(second)
    if scenario == "write_failure":

        def fail_replace(src: Path, dst: Path) -> None:
            raise OSError("disk error")

        monkeypatch.setattr("os.replace", fail_replace)
    result = run_csv(
        inputs=inputs, output=output, transform=transform, validate=validate_activity, overwrite=overwrite
    )
    assert source.read_bytes() == original
    if scenario == "overwrite":
        assert result is not None
        first = output.read_bytes()
        assert (
            run_csv(
                inputs=inputs, output=output, transform=transform, validate=validate_activity, overwrite=True
            )
            is not None
        )
        assert output.read_bytes() == first
    else:
        assert result is None
        assert output.read_bytes() == (original if scenario == "same_input" else b"existing")
    if scenario == "existing":
        assert "EtlOutputError" in caplog.text
        assert f"Output exists: {output}; set overwrite=True" in caplog.text
    if scenario == "same_input":
        assert "EtlOutputError" in caplog.text
        assert f"Output overlaps an input: {source}" in caplog.text
    if scenario == "no_inputs":
        assert "EtlInputError" in caplog.text
        assert "provide at least one input path" in caplog.text
    assert not list(tmp_path.glob("tmp*.csv"))


@pytest.mark.parametrize("scenario", ["plain", "report", "validation_failure", "publication_failure"])
def test_run_task_executes_unrelated_dataset(tmp_path: Path, scenario: str) -> None:
    runner = import_module("etl.runner")
    source = tmp_path / "codes.csv"
    output = tmp_path / "output.csv"
    reported = []
    source.write_text("code\n01260\n", encoding="utf-8")
    if scenario == "publication_failure":
        output.write_text("existing", encoding="utf-8")

    def clean(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.rename(columns={"code": "identifier"})

    def validate(frame: pd.DataFrame) -> None:
        if scenario == "validation_failure":
            raise import_module("etl.errors").EtlValidationError("Rejected identifier")
        assert frame.identifier.tolist() == ["01260"]

    def report(frame: pd.DataFrame) -> None:
        published = pd.read_csv(output, dtype="string")
        assert published.identifier.tolist() == frame.identifier.tolist()
        reported.extend(frame.identifier.tolist())

    task = runner.TaskDefinition(
        inputs=[source],
        output=output,
        transform=clean,
        validate=None if scenario == "plain" else validate,
        report=None if scenario == "plain" else report,
    )
    success = scenario in ("plain", "report")
    assert runner.run_task(task) is success
    assert reported == (["01260"] if scenario == "report" else [])
    if scenario == "validation_failure":
        assert not output.exists()
    if scenario == "publication_failure":
        assert output.read_text(encoding="utf-8") == "existing"
