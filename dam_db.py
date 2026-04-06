"""
DAM DB — shared database connection helper.

Provides a single get_db() used by dam_api, dam_tagger, and dam_schema.
"""

import sqlite3
import struct

import sqlite_vec

import dam_config


def get_db():
    """Open a connection to the DAM database with WAL mode and sqlite-vec loaded."""
    conn = sqlite3.connect(str(dam_config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def serialize_vector(floats: list) -> bytes:
    """Pack float list to binary blob for sqlite-vec."""
    return struct.pack(f"{len(floats)}f", *floats)


def wal_checkpoint(conn=None):
    """Truncate the WAL file after bulk operations. Pass an open conn or None to open/close one."""
    if conn is None:
        conn = get_db()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
    else:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
