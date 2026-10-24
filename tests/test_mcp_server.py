import sqlite3
from contextlib import closing
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List

import pytest


@pytest.mark.parametrize("filters,expected", [
    ({"state_code": "fl"}, [1, 2]),
    ({"airport_code": "mia"}, [1]),
    ({"name": "INTERNATIONAL", "state_code": "FL"}, [1, 2]),
    ({"name": "Miami"}, [1]),
    ({"name": "%"}, []),
    ({"state_code": "FL' OR 1=1 --"}, []),
    ({"state_code": "FL", "airport_code": "LAX"}, []),
])
def test_lookup_airports_filters_parameterized_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                  filters: Dict[str, Any], expected: List[int]) -> None:
    dao = import_module("analysis.dao_get_gold_data")
    server = import_module("mcp_server")
    database = tmp_path / "gold.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.executescript("""
            CREATE TABLE airport_dimension(canonical_airport_id INTEGER, airport_code TEXT,
                                           name TEXT, state_code TEXT);
            INSERT INTO airport_dimension VALUES
                (1,'MIA','Miami International','FL'),(2,'MCO','Orlando International','FL'),
                (3,'LAX','Los Angeles International','CA');
        """)
        connection.commit()
    monkeypatch.setattr(dao, "GOLD_DATABASE_PATH", database)
    rows = server.lookup_airports(**filters)
    assert [row.get("canonical_airport_id") for row in rows] == expected
    assert all(row.get("airport_code") and row.get("name") for row in rows)


@pytest.mark.parametrize("filters", [{}, {"name": " "}, {"state_code": ""}])
def test_lookup_airports_requires_nonblank_filters(filters: Dict[str, Any]) -> None:
    server = import_module("mcp_server")
    with pytest.raises(server.ToolError):
        server.lookup_airports(**filters)
