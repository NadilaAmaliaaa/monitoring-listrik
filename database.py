from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from config import Config

# Create database engine
engine = create_engine(
    Config.SQLALCHEMY_DATABASE_URI,
    echo=False,
    pool_pre_ping=True,       # verify connection sebelum dipakai
    pool_size=20,             # koneksi persistent di pool
    max_overflow=10,          # koneksi tambahan saat pool penuh (total max 30)
    pool_recycle=1800,        # recycle tiap 30 menit (lebih agresif dari 1 jam)
    pool_timeout=10,          # timeout tunggu koneksi dari pool (detik)
)

# Scoped session — dipakai untuk request Flask via close_db()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db_session = scoped_session(SessionLocal)

Base = declarative_base()


# ── Session helpers ───────────────────────────────────────────────────────────

def get_session():
    """
    Buat session baru yang TIDAK terikat scoped_session.
    Caller wajib menutup sendiri via session.close() atau pakai context manager.

    Contoh pakai (wajib):
        session = get_session()
        try:
            ...
        finally:
            session.close()   # kembalikan koneksi ke pool

    Atau pakai context manager:
        with get_session() as session:
            ...
    """
    return SessionLocal()


def get_request_session():
    """
    Session yang terikat ke Flask request context (scoped).
    Otomatis di-remove oleh close_db() di teardown_appcontext.
    Gunakan ini di dalam route/controller Flask.
    """
    return db_session()


def close_db(exception=None):
    """
    Dipanggil oleh @app.teardown_appcontext.
    Remove scoped session — kembalikan koneksi ke pool.
    """
    db_session.remove()


def init_db():
    from models.data import Sensor, SensorReading, SensorThreshold, AlarmEvent
    from models.building import Building
    from models.views import HourlyEnergyView, DailyEnergyView

    Base.metadata.create_all(bind=engine)
    print("✓ Database tables created successfully")


db = Base