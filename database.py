from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session
from config import Config

# Create engine
engine = create_engine(
    Config.SQLALCHEMY_DATABASE_URI,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Verify connections before using
    echo=Config.SQLALCHEMY_ECHO
)

# Create session factory
SessionFactory = sessionmaker(bind=engine)
Session = scoped_session(SessionFactory)

def get_session():
    """Get database session"""
    return Session()

def init_db():
    """Initialize database and create TimescaleDB hypertables"""
    from models.energy import Base, SensorData
    from models.alarm import Alarm
    
    # Create all tables
    Base.metadata.create_all(engine)

def close_db():
    """Close database connection"""
    Session.remove()