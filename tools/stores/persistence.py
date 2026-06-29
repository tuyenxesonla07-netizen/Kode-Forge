"""
tools/stores/persistence.py

SQLite persistence backend for all stores.
Provides a lightweight, file-based storage layer so that
requirements, interfaces, and specs survive process restarts.
"""

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Optional


class StoreDatabase:
    """Shared SQLite database for all store types."""

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS store_data (
            key TEXT NOT NULL,
            store_type TEXT NOT NULL,
            data TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (key, store_type)
        );
        CREATE INDEX IF NOT EXISTS idx_store_type ON store_data(store_type);
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(Path(__file__).parent.parent / "data" / "stores.db")
        self._db_path = db_path
        self._lock = threading.Lock()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(self.SCHEMA)
        self._conn.commit()

    def put(self, store_type: str, key: str, data: Any) -> None:
        with self._lock:
            serialized = json.dumps(data, ensure_ascii=False, default=str)
            self._conn.execute(
                "INSERT OR REPLACE INTO store_data (key, store_type, data) VALUES (?, ?, ?)",
                (key, store_type, serialized),
            )
            self._conn.execute(
                "UPDATE store_data SET updated_at = datetime('now') WHERE key = ?",
                (key,),
            )
            self._conn.commit()

    def get(self, store_type: str, key: str) -> Optional[Any]:
        row = self._conn.execute(
            "SELECT data FROM store_data WHERE key = ? AND store_type = ?",
            (key, store_type),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def get_all(self, store_type: str) -> Dict[str, Any]:
        rows = self._conn.execute(
            "SELECT key, data FROM store_data WHERE store_type = ?",
            (store_type,),
        ).fetchall()
        return {row[0]: json.loads(row[1]) for row in rows}

    def delete(self, store_type: str, key: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM store_data WHERE key = ? AND store_type = ?",
            (key, store_type),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def clear(self, store_type: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM store_data WHERE store_type = ?", (store_type,))
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self) -> None:
        try:
            self._conn.close()
        except Exception as e:
            logging.getLogger(__name__).debug("DB close error: %s", e)
