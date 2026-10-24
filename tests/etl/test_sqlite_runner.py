import sqlite3
from importlib import import_module
from pathlib import Path
from typing import Callable, Tuple

import pytest

runner = import_module("etl.runner")


@pytest.mark.parametrize("scenario", ["publish", "invalid", "overwrite", "existing", "missing", "overlap",
                                      "no_inputs", "locked", "replace_failure", "unexpected", "foreign_key",
                                      "integrity", "wal_callback", "race"])
def test_run_generated_sqlite_publishes_complete_database(
    tmp_path: Path, scenario: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "input.csv"
    output = tmp_path / "gold.db"
    source.write_text("code\nA\n", encoding="utf-8")
    paths = [source]
    overwrite = scenario in ["invalid", "overwrite", "replace_failure", "unexpected", "foreign_key", "integrity"]
    if overwrite or scenario == "existing":
        output.write_bytes(b"previous database")
    if scenario == "missing":
        paths = [tmp_path / "missing.csv"]
    if scenario == "no_inputs":
        paths = []
    if scenario == "overlap":
        output = source
    if scenario == "locked":
        output.with_name(output.name + ".lock").write_text("other publisher", encoding="utf-8")
    if scenario == "replace_failure":
        def fail_replace(src: Path, dst: Path) -> None:
            raise PermissionError("Database is open in another application")
        monkeypatch.setattr("os.replace", fail_replace)

    build, validate = _callbacks(scenario=scenario, output=output)
    if scenario == "unexpected":
        with pytest.raises(RuntimeError, match="Unexpected callback failure"):
            runner.run_generated_sqlite(inputs=paths, output=output, build=build, validate=validate, overwrite=overwrite)
        _assert_publication_files(tmp_path=tmp_path, scenario=scenario)
        assert output.read_bytes() == b"previous database"
        return
    success = runner.run_generated_sqlite(inputs=paths, output=output, build=build, validate=validate, overwrite=overwrite)
    _assert_result(output=output, scenario=scenario, success=success)
    _assert_publication_files(tmp_path=tmp_path, scenario=scenario)


def _callbacks(scenario: str, output: Path) -> Tuple[Callable, Callable]:
    def build(connection: sqlite3.Connection) -> None:
        if scenario == "wal_callback":
            connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE airports (id INTEGER PRIMARY KEY CHECK(id > 0))")
        connection.execute("INSERT INTO airports VALUES (1)")
        if scenario == "unexpected":
            raise RuntimeError("Unexpected callback failure")
        if scenario == "foreign_key":
            connection.execute("PRAGMA defer_foreign_keys=ON")
            connection.execute("CREATE TABLE children (id INTEGER REFERENCES airports(id))")
            connection.execute("INSERT INTO children VALUES (99)")
        if scenario == "integrity":
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute("UPDATE airports SET id=-1")

    def validate(connection: sqlite3.Connection) -> None:
        assert connection.execute("SELECT COUNT(*) FROM airports").fetchone() == (1,)
        if scenario == "invalid":
            raise import_module("etl.errors").EtlValidationError("Rejected fixture")
        if scenario == "race":
            output.write_bytes(b"previous database")
    return build, validate


def _assert_result(output: Path, scenario: str, success: bool) -> None:
    assert success is (scenario in ["publish", "overwrite", "wal_callback"])
    if success:
        connection = sqlite3.connect(output)
        assert connection.execute("SELECT * FROM airports").fetchall() == [(1,)]
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        connection.close()
    elif output.exists():
        assert output.read_text(encoding="utf-8") == ("code\nA\n" if scenario == "overlap" else "previous database")


def _assert_publication_files(tmp_path: Path, scenario: str) -> None:
    names = sorted(path.name for path in tmp_path.iterdir())
    expected = ["input.csv"]
    if scenario not in ["missing", "no_inputs", "overlap", "locked"]:
        expected.insert(0, "gold.db")
    if scenario == "locked":
        expected.insert(0, "gold.db.lock")
        assert (tmp_path / "gold.db.lock").read_text(encoding="utf-8") == "other publisher"
    assert names == expected
