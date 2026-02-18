"""
Database models untuk energy monitoring system
"""

from datetime import datetime
from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, String, Index
from sqlalchemy.orm import relationship
from database import Base  # Import Base, bukan db


class Sensor(Base):
    """Model untuk sensor"""
    __tablename__ = "sensors"

    id = Column(Integer, primary_key=True)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=False)
    name = Column(String(100), nullable=False)
    phase = Column(String(1), nullable=False)  # R, S, or T
    # description = Column(String(255))
    # created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    building = relationship("Building", back_populates="sensors")
    readings = relationship("SensorReading", back_populates="sensor", cascade="all, delete-orphan")
    thresholds = relationship("SensorThreshold", back_populates="sensor", cascade="all, delete-orphan")
    alarms = relationship("AlarmEvent", back_populates="sensor", cascade="all, delete-orphan")
    # daily = relationship("DailyEnergyView", back_populates="sensor", cascade="all, delete-orphan")
    # hourly = relationship("HourlyEnergyView", back_populates="sensor", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Sensor(id={self.id}, name='{self.name}', phase='{self.phase}')>"


class SensorReading(Base):
    """Model untuk sensor readings - data yang tersimpan"""
    __tablename__ = "sensor_readings"

    # Composite primary key
    sensor_id = Column(Integer, ForeignKey("sensors.id"), primary_key=True)
    timestamp = Column(DateTime, primary_key=True, default=datetime.utcnow)

    # Electrical measurements
    voltage = Column(Float, nullable=False)
    current = Column(Float, nullable=False)
    power = Column(Float, nullable=False)
    frequency = Column(Float, nullable=False)
    power_factor = Column(Float, nullable=False)
    energy = Column(Float, nullable=False)

    # Peak values (untuk monitoring)
    peak_voltage = Column(Float)
    peak_current = Column(Float)

    # Relationships
    sensor = relationship("Sensor", back_populates="readings")
    
    # Indexes untuk performa query
    __table_args__ = (
        Index("idx_sensor_time", "sensor_id", "timestamp"),
        Index("idx_time", "timestamp"),
    )
    
    def __repr__(self):
        return f"<SensorReading(sensor_id={self.sensor_id}, timestamp={self.timestamp})>"
