from __future__ import annotations

from contextlib import contextmanager

import mysql.connector
from mysql.connector import Error


@contextmanager
def get_conn(app):
    """Context manager that yields a MySQL connection.

    Uses Flask app config keys:
      DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_PORT
    """
    conn = None
    try:
        conn = mysql.connector.connect(
            host=app.config["DB_HOST"],
            user=app.config["DB_USER"],
            password=app.config["DB_PASSWORD"],
            database=app.config["DB_NAME"],
            port=app.config["DB_PORT"],
        )
        yield conn
    finally:
        if conn is not None and conn.is_connected():
            conn.close()


def db_error_message(exc: Exception) -> str:
    # Keep messages beginner-friendly but useful.
    if isinstance(exc, Error):
        return f"Database error: {exc.msg}"
    return f"Unexpected error: {str(exc)}"
