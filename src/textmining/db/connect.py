import sqlite3
from pathlib import Path
from textmining.paths import DB_DIR
import logging

SCHEMA_PATH = Path(__file__).parent / "schema" / "core.sql"
DB_PATH = DB_DIR / "atlas.db"
logger = logging.getLogger(__name__)


def _configure(con: sqlite3.Connection) -> None:
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")

def open_for_build(path: Path = DB_PATH) -> sqlite3.Connection:
    path.unlink(missing_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Building %s from %s", path, SCHEMA_PATH)
    con = sqlite3.connect(f"file:{path}?mode=rwc", uri=True)
    cursor = con.cursor()
    cursor.executescript(SCHEMA_PATH.read_text())
    con.commit()
    _configure(con)

    n_tables = con.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
    if n_tables == 0:
        raise RuntimeError(f"{SCHEMA_PATH} created no tables — is it empty?")
    logger.info("Schema applied: %d table(s)", n_tables)
    return con

def open_readonly(path: Path = DB_PATH) -> sqlite3.Connection:
    logger.info("Opening %s read-only", path)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    _configure(con)
    return con