"""
SQLite price history store.

Schema:
  products       — one row per tracked URL
  snapshots      — one row per fetch run per product
  variant_prices — one row per variant per snapshot
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import ProductSnapshot, Variant

DB_PATH = Path(__file__).parent / "prices.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS products (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                url     TEXT    UNIQUE NOT NULL,
                name    TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id  INTEGER NOT NULL REFERENCES products(id),
                captured_at TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS variant_prices (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id),
                attr_key     TEXT    NOT NULL,
                attributes   TEXT    NOT NULL,  -- JSON
                price        REAL    NOT NULL,
                msrp         REAL,
                in_stock     INTEGER NOT NULL DEFAULT 1,
                currency     TEXT    NOT NULL DEFAULT 'USD'
            );
        """)


def save_snapshot(snapshot: ProductSnapshot) -> None:
    """Persist a ProductSnapshot to the database."""
    with _connect() as conn:
        # Upsert product
        conn.execute(
            "INSERT OR IGNORE INTO products (url, name) VALUES (?, ?)",
            (snapshot.url, snapshot.product_name),
        )
        # Update name in case it changed
        conn.execute(
            "UPDATE products SET name = ? WHERE url = ?",
            (snapshot.product_name, snapshot.url),
        )
        product_id = conn.execute(
            "SELECT id FROM products WHERE url = ?", (snapshot.url,)
        ).fetchone()["id"]

        captured_at = (snapshot.captured_at or datetime.utcnow()).isoformat()
        cursor = conn.execute(
            "INSERT INTO snapshots (product_id, captured_at) VALUES (?, ?)",
            (product_id, captured_at),
        )
        snapshot_id = cursor.lastrowid

        for v in snapshot.variants:
            conn.execute(
                """INSERT INTO variant_prices
                   (snapshot_id, attr_key, attributes, price, msrp, in_stock, currency)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    v.attr_key,
                    json.dumps(v.attributes),
                    v.price,
                    v.msrp,
                    int(v.in_stock),
                    v.currency,
                ),
            )


def get_previous_snapshot(url: str) -> ProductSnapshot | None:
    """Return the second-most-recent snapshot for a URL (i.e. the one before latest)."""
    with _connect() as conn:
        product_row = conn.execute(
            "SELECT id, name FROM products WHERE url = ?", (url,)
        ).fetchone()
        if not product_row:
            return None

        snapshots = conn.execute(
            """SELECT id, captured_at FROM snapshots
               WHERE product_id = ?
               ORDER BY captured_at DESC LIMIT 2""",
            (product_row["id"],),
        ).fetchall()

        if len(snapshots) < 2:
            return None  # No previous snapshot to compare against

        prev_snapshot_id = snapshots[1]["id"]
        prev_captured_at = snapshots[1]["captured_at"]

        rows = conn.execute(
            "SELECT * FROM variant_prices WHERE snapshot_id = ?",
            (prev_snapshot_id,),
        ).fetchall()

        variants = [
            Variant(
                attributes=json.loads(r["attributes"]),
                price=r["price"],
                msrp=r["msrp"],
                in_stock=bool(r["in_stock"]),
                currency=r["currency"],
            )
            for r in rows
        ]
        return ProductSnapshot(
            product_name=product_row["name"],
            url=url,
            variants=variants,
            captured_at=datetime.fromisoformat(prev_captured_at),
        )
