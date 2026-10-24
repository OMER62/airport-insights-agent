import sqlite3
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List

import pytest

dao_get_gold_data = import_module("analysis.dao_get_gold_data")
get_gold_data = dao_get_gold_data.get_gold_data


@pytest.mark.parametrize("value", [7, "O'Hare", "' OR 1=1 --"])
def test_get_gold_data_binds_parameters(value: int | str) -> None:
    assert get_gold_data(query="SELECT :value AS value", parameters={"value": value}) == [{"value": value}]


@pytest.mark.parametrize("query,expected,missing_database", [
    ("SELECT 1 AS airport_id, 'JFK' AS airport_code, NULL AS missing",
     [{"airport_id": 1, "airport_code": "JFK", "missing": None}], False),
    ("SELECT airport_code FROM airport_dimension LIMIT 0", [], False),
    ("SELECT 1 AS value UNION ALL SELECT 2", [{"value": 1}, {"value": 2}], False),
    ("INVALID SQL", None, False),
    ("SELECT * FROM missing_table", None, False),
    ("UPDATE airport_dimension SET airport_code = airport_code WHERE 0", None, False),
    ("SELECT 1", None, True),
])
def test_get_gold_data(
    query: str, expected: List[Dict[str, Any]] | None, missing_database: bool,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_path = tmp_path / "missing.db"
    monkeypatch.chdir(tmp_path)
    if missing_database:
        monkeypatch.setattr(target=dao_get_gold_data, name="GOLD_DATABASE_PATH", value=missing_path)
    if expected is None:
        with pytest.raises(sqlite3.Error):
            get_gold_data(query=query)
        assert not missing_path.exists()
        return
    assert get_gold_data(query=query) == expected
