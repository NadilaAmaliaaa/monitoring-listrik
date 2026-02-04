from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from config import Config

# Create database engine
engine = create_engine(
    Config.SQLALCHEMY_DATABASE_URI,
    echo=False,  # Set True untuk debug SQL queries
    pool_pre_ping=True,  # Verify connections before using
    pool_size=Config.DB_POOL_MAXCONN,
    max_overflow=10,
    pool_recycle=3600  # Recycle connections after 1 hour
)

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Create scoped session for thread safety
db_session = scoped_session(SessionLocal)

# Create declarative base for models
Base = declarative_base()


# ==================== HELPER FUNCTIONS ====================

def get_session():
    return SessionLocal()


def close_db(exception=None):
    db_session.remove()


def init_db():
    # Import all models to ensure they are registered
    from models.data import Sensor, SensorReading, SensorThreshold, AlarmEvent
    from models.building import Building
    from models.views import HourlyEnergyView, DailyEnergyView
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    print("✓ Database tables created successfully")


# def drop_db():
#     Base.metadata.drop_all(bind=engine)
#     print("✓ All tables dropped")


# Alias for compatibility
db = Base