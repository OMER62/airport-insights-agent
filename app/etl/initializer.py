from pathlib import Path
from typing import Callable, List

import pandas as pd

from .runner import TaskDefinition, run_generated_csv, run_generated_sqlite, run_partitioned_csv, run_task


def initialize_generated(**kwargs) -> bool:
    """Submit a multi-source CSV build to the runner."""
    return run_generated_csv(**kwargs)


def initialize_partitions(**kwargs) -> bool:
    """Submit a bounded-memory partitioned CSV task."""
    return run_partitioned_csv(**kwargs)


def initialize_sqlite(inputs: List[Path], output: Path, build: Callable, validate: Callable,
                      overwrite: bool = False) -> bool:
    return run_generated_sqlite(inputs=inputs, output=output, build=build, validate=validate, overwrite=overwrite)


def create_task(
    inputs: List[Path],
    output: Path,
    transform: Callable[[pd.DataFrame], pd.DataFrame],
    validate: Callable[[pd.DataFrame], None] | None = None,
    report: Callable[[pd.DataFrame], None] | None = None,
    overwrite: bool = False,
) -> TaskDefinition:
    return TaskDefinition(
        inputs=inputs,
        output=output,
        transform=transform,
        validate=validate,
        report=report,
        overwrite=overwrite,
    )


def initialize(
    inputs: List[Path],
    output: Path,
    transform: Callable[[pd.DataFrame], pd.DataFrame],
    validate: Callable[[pd.DataFrame], None] | None = None,
    report: Callable[[pd.DataFrame], None] | None = None,
    overwrite: bool = False,
) -> bool:
    """Create and run a CSV task - return the runner's success or failure."""
    task = create_task(
        inputs=inputs,
        output=output,
        transform=transform,
        validate=validate,
        report=report,
        overwrite=overwrite,
    )
    return run_task(task)
