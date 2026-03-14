"""
DAM DB — shared database connection helper.

Provides a single get_db() used by dam_api, dam_tagger, and dam_schema.
"""

import sqlite3

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
