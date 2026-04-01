import os


class Config:
    # Flask
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")

    # MySQL
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_USER = os.environ.get("DB_USER", "root")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
    DB_NAME = os.environ.get("DB_NAME", "library_db")
    DB_PORT = int(os.environ.get("DB_PORT", "3306"))

    # Fine calculation
    # Fine amount = days_overdue * DAILY_FINE_RATE
    DAILY_FINE_RATE = float(os.environ.get("DAILY_FINE_RATE", "5"))
