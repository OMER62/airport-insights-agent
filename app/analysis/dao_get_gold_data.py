import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from pprint import pprint
from typing import Any, Dict, List

GOLD_DATABASE_PATH = Path(__file__).resolve().parents[2] / "data/gold/airport_gold.db"
log_ = logging.getLogger("etl")


def get_gold_data(query: str, parameters: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """Read gold data as dictionaries - SQLite errors propagate and the database stays read-only."""
    database_uri = f"{GOLD_DATABASE_PATH.as_uri()}?mode=ro"
    try:
        with closing(sqlite3.connect(database=database_uri, uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(query, parameters or {}).fetchall()]
    except sqlite3.Error as error:
        log_.error(f"Gold database query failed: {error}")
        raise


if __name__ == "__main__":
    pprint(get_gold_data(query="SELECT * FROM airport_dimension"))
