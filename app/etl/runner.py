import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Callable, List

import pandas as pd

from . import log_
from .errors import EtlError, EtlInputError, EtlOutputError, EtlValidationError


class TaskDefinition:
    def __init__(
        self,
        inputs: List[Path],
        output: Path,
        transform: Callable[[pd.DataFrame], pd.DataFrame],
        validate: Callable[[pd.DataFrame], None] | None = None,
        report: Callable[[pd.DataFrame], None] | None = None,
        overwrite: bool = False,
    ) -> None:
        self.inputs = inputs
        self.output = output
        self.transform = transform
        self.validate = validate
        self.report = report
        self.overwrite = overwrite


def _write_csv(frame: pd.DataFrame, output: Path, overwrite: bool) -> None:
    """Stage and publish a CSV - failures leave existing output intact."""
    temporary = None
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", suffix=".csv", dir=output.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            frame.to_csv(path_or_buf=stream, index=False)
        if overwrite:
            os.replace(src=temporary, dst=output)
        else:
            os.link(src=temporary, dst=output)  # Exclusive publication protects concurrent runs.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_csv(
    inputs: List[Path],
    output: Path,
    transform: Callable[[pd.DataFrame], pd.DataFrame],
    validate: Callable[[pd.DataFrame], None] | None = None,
    overwrite: bool = False,
) -> pd.DataFrame | None:
    """Transform CSV files into one output - return None after logging an expected failure."""
    frames: List[pd.DataFrame] = []
    try:
        if not inputs:
            raise EtlInputError("No input CSV files supplied; provide at least one input path")
        if any(path.resolve() == output.resolve() for path in inputs):
            raise EtlOutputError(f"Output overlaps an input: {output}; choose a different output path")
        if output.exists() and not overwrite:
            raise EtlOutputError(f"Output exists: {output}; set overwrite=True to replace it")
        for path in inputs:
            frame = pd.read_csv(
                filepath_or_buffer=path, dtype="string", keep_default_na=False, encoding="utf-8-sig"
            )
            frames.append(transform(frame))
        result = pd.concat(objs=frames, ignore_index=True)
        if validate is not None:
            validate(result)
        _write_csv(frame=result, output=output, overwrite=overwrite)
    except (EtlError, OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
        log_.exception(f"CSV ETL failed for {output}: {error}")
        return None
    log_.info(f"Wrote {len(result):,} rows to {output}")
    return result


def run_task(task: TaskDefinition) -> bool:
    """Execute a CSV task - report only after successful validation and publication."""
    result = run_csv(
        inputs=task.inputs,
        output=task.output,
        transform=task.transform,
        validate=task.validate,
        overwrite=task.overwrite,
    )
    if result is None:
        return False
    if task.report is not None:
        task.report(result)
    return True


def run_generated_csv(inputs, output, build, validate=None, overwrite=False):
    """Build one CSV from heterogeneous sources, validating before atomic publication."""
    output = Path(output)
    try:
        if not inputs:
            raise EtlInputError("No input files supplied")
        for path in map(Path, inputs):
            if not path.is_file():
                raise EtlInputError(f"Missing input: {path}")
            if path.resolve() == output.resolve():
                raise EtlOutputError(f"Output overlaps input: {path}")
        if output.exists() and not overwrite:
            raise EtlOutputError(f"Output exists: {output}; set overwrite=True to replace it")
        result = build()
        if validate is not None:
            validate(result)
        _write_csv(result, output, overwrite)
    except (EtlError, OSError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
        log_.exception(f"Generated CSV ETL failed for {output}: {error}")
        return False
    log_.info(f"Wrote {len(result):,} rows to {output}")
    return True


def _check_sqlite_inputs(inputs: List[Path], output: Path, overwrite: bool) -> None:
    if not inputs:
        raise EtlInputError("No input files supplied")
    for path in inputs:
        if path.resolve() == output.resolve():
            raise EtlOutputError(f"Output overlaps input: {path}")
        if not path.is_file():
            raise EtlInputError(f"Missing input: {path}")
    if output.exists() and not overwrite:
        raise EtlOutputError(f"Output exists: {output}; set overwrite=True to replace it")


def _build_sqlite_stage(stage: Path, build: Callable[[sqlite3.Connection], None],
                        validate: Callable[[sqlite3.Connection], None]) -> None:
    with closing(sqlite3.connect(database=stage)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA cache_size=-32768")
        connection.execute("PRAGMA temp_store=FILE")
        with connection:
            build(connection)
            validate(connection)
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("VACUUM")
    with closing(sqlite3.connect(database=stage)) as connection:
        connection.execute("PRAGMA query_only=ON")  # Read-only URI mode skips CHECK validation in SQLite.
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise EtlValidationError("Staged SQLite database failed integrity_check")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise EtlValidationError("Staged SQLite database failed foreign_key_check")


def run_generated_sqlite(inputs: List[Path], output: Path, build: Callable[[sqlite3.Connection], None],
                         validate: Callable[[sqlite3.Connection], None],
                         overwrite: bool = False) -> bool:
    """Build a staged database - failed validation or replacement preserves the published file."""
    output = Path(output).resolve()
    paths = [Path(path) for path in inputs]
    lock = output.with_name(output.name + ".lock")
    stage = None
    acquired = False
    try:
        _check_sqlite_inputs(inputs=paths, output=output, overwrite=overwrite)
        output.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("x"):
            acquired = True
        with tempfile.NamedTemporaryFile(suffix=".db", prefix=".gold-", dir=output.parent, delete=False) as stream:
            stage = Path(stream.name)
        _build_sqlite_stage(stage=stage, build=build, validate=validate)
        if overwrite:
            os.replace(src=stage, dst=output)
        else:
            os.link(src=stage, dst=output)
    except (EtlError, OSError, UnicodeError, sqlite3.Error, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
        log_.exception(f"SQLite ETL failed for {output}: {error}")
        return False
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)
            stage.with_name(stage.name + "-journal").unlink(missing_ok=True)
        if acquired:
            lock.unlink(missing_ok=True)
    log_.info(f"Published SQLite database: {output}")
    return True


def run_partitioned_csv(inputs, output, columns, key, transform, report=None, overwrite=False, chunksize=50000):
    """Stage a complete directory with disk-backed key validation, then publish with rollback.

    inputs maps partition names to paths. transform receives a chunk and partition name.
    A sibling lock excludes concurrent publishers; a retained backup supports recovery
    after an interrupted directory swap. Existing single-output tasks are unaffected.
    """
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = output.with_name(output.name + ".lock")
    backup = output.with_name(output.name + ".backup")
    acquired = False
    try:
        with lock.open("x"):
            acquired = True
        if backup.exists():
            raise EtlOutputError(f"Recovery required: inspect retained backup {backup} before retrying")
        if output.exists() and not overwrite:
            raise EtlOutputError(f"Output exists: {output}; set overwrite=True to replace it")
        if not inputs or chunksize <= 0:
            raise EtlInputError("Supply partitions and a positive chunksize")
        for path in inputs.values():
            if not path.is_file():
                raise EtlInputError(f"Missing input: {path}")
            if output == path.resolve() or output in path.resolve().parents:
                raise EtlOutputError(f"Input overlaps output directory: {path}")
        with tempfile.TemporaryDirectory(prefix=output.name + "-", dir=output.parent) as temporary:
            stage = Path(temporary) / "data"
            stage.mkdir()
            with closing(sqlite3.connect(str(Path(temporary) / "keys.sqlite"))) as database:
                database.execute("PRAGMA cache_size=-8192")
                database.execute("CREATE TABLE keys (value TEXT PRIMARY KEY) WITHOUT ROWID")
                for partition, path in inputs.items():
                    header = pd.read_csv(path, nrows=0, encoding="utf-8-sig")
                    missing = set(columns) - set(header.columns)
                    if missing:
                        raise EtlValidationError(f"{path}: missing required columns {sorted(missing)}")
                    count = 0
                    for chunk in pd.read_csv(path, usecols=list(columns), dtype="string", keep_default_na=False,
                                             encoding="utf-8-sig", chunksize=chunksize):
                        frame = transform(chunk, partition)
                        if len(frame) != len(chunk):
                            raise EtlValidationError(f"{path}: transformation changed row count")
                        try:
                            database.executemany("INSERT INTO keys VALUES (?)", (
                                (json.dumps(list(row), separators=(",", ":")),)
                                for row in frame[key].astype("string").itertuples(index=False, name=None)
                            ))
                        except sqlite3.IntegrityError as error:
                            raise EtlValidationError(f"{path}: duplicate business key within or across chunks/inputs") from error
                        frame.to_csv(stage / f"{partition}.csv", mode="a", header=count == 0, index=False)
                        if report:
                            report(frame, partition)
                        count += len(frame)
                    if not count:
                        raise EtlValidationError(f"Empty partition: {path}")
                    database.commit()
                    log_.info(f"Validated and staged {partition}: {count:,} rows from {path}")
            had_output = output.exists()
            if had_output:
                os.replace(output, backup)
            try:
                os.replace(stage, output)
            except BaseException:
                if had_output:
                    os.replace(backup, output)
                raise
            if had_output:
                try:
                    shutil.rmtree(backup)
                except OSError:
                    log_.warning(f"Output published; old backup cleanup required: {backup}")
        log_.info(f"Published complete output set: {output}")
        return True
    except (EtlError, OSError, UnicodeError, sqlite3.Error, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
        log_.exception(f"Partitioned ETL failed for {output}: {error}")
        return False
    finally:
        if acquired:
            lock.unlink(missing_ok=True)
