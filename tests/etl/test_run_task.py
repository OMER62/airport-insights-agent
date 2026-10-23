from importlib import import_module
from pathlib import Path

import pandas as pd
import pytest
from test_flight_activity import ROW

activity = import_module("etl.tasks.t1_flight_activity")


@pytest.mark.parametrize("invalid", [False, True])
def test_flight_task_preserves_validation_and_overwrite(
    tmp_path: Path, invalid: bool, caplog: pytest.LogCaptureFixture
) -> None:
    source = tmp_path / "input.csv"
    output = tmp_path / "output.csv"
    row = {**ROW, "MONTH": "13"} if invalid else ROW
    pd.DataFrame([row]).to_csv(path_or_buf=source, index=False)
    with caplog.at_level("INFO", logger="etl"):
        result = activity.run(inputs=[source], output=output)
    assert result is not invalid
    assert output.exists() is not invalid
    assert ("flag_invalid_distance:" in caplog.text) is not invalid
    if not invalid:
        actual = pd.read_csv(output, dtype="string")
        assert actual.carrier_entity.tolist() == ["01260"]
        assert activity.run(inputs=[source], output=output) is False
        assert activity.run(inputs=[source], output=output, overwrite=True) is True
