import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

class Config:
    # ========================
    # Flask Core
    # ========================
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")

    # ========================
    # PostgreSQL / TimescaleDB
    # ========================
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME")
    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")

    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False

    # ========================
    # Upload
    # ========================
    UPLOAD_FOLDER = "uploads/reports"
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

    # ========================
    # Pagination
    # ========================
    ITEMS_PER_PAGE = int(os.getenv("ITEMS_PER_PAGE", 10))

    # ========================
    # IoT Power Quality Thresholds
    # ========================
    # VOLTAGE_MIN = float(os.getenv("VOLTAGE_MIN", 200.0))
    # VOLTAGE_MAX = float(os.getenv("VOLTAGE_MAX", 240.0))

    # CURRENT_MIN = float(os.getenv("CURRENT_MIN", 5.0))
    # CURRENT_MAX = float(os.getenv("CURRENT_MAX", 50.0))

    # FREQUENCY_MIN = float(os.getenv("FREQUENCY_MIN", 49.5))
    # FREQUENCY_MAX = float(os.getenv("FREQUENCY_MAX", 50.5))

    # POWER_FACTOR_MIN = float(os.getenv("POWER_FACTOR_MIN", 0.85))
