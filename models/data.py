"""
Database models untuk energy monitoring system
"""

from datetime import datetime
from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, String, Index
from sqlalchemy.orm import relationship
from database import Base  # Import Base, bukan db


class Building(Base):
    __tablename__ = "buildings"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    code = Column(String(50), nullable=False, unique=True)
    address = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    sensors = relationship("Sensor", back_populates="building", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Building(id={self.id}, name='{self.name}', code='{self.code}')>"


class Sensor(Base):
    """Model untuk sensor"""
    __tablename__ = "sensors"

    id = Column(Integer, primary_key=True)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=False)
    name = Column(String(100), nullable=False)
    phase = Column(String(1), nullable=False)  # R, S, or T
    description = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)

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


class SensorThreshold(Base):
    """Model untuk threshold/batas nilai sensor"""
    __tablename__ = "sensor_thresholds"

    id = Column(Integer, primary_key=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=False)

    # Threshold values
    voltage_min = Column(Float)
    voltage_max = Column(Float)
    current_min = Column(Float)
    current_max = Column(Float)
    power_min = Column(Float)
    power_max = Column(Float)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    sensor = relationship("Sensor", back_populates="thresholds")
    
    def __repr__(self):
        return f"<SensorThreshold(id={self.id}, sensor_id={self.sensor_id})>"


class AlarmEvent(Base):
    """Model untuk alarm events"""
    __tablename__ = "alarm_events"

    id = Column(Integer, primary_key=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=False)

    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    parameter = Column(String(50))  # voltage, current, power, etc.
    actual_value = Column(Float)
    threshold_min = Column(Float)
    threshold_max = Column(Float)
    status = Column(String(20))  # LOW, HIGH, NORMAL
    message = Column(String(255))
    acknowledged = Column(Integer, default=0)  # 0=not ack, 1=acknowledged
    acknowledged_at = Column(DateTime)
    acknowledged_by = Column(String(100))

    # Relationships
    sensor = relationship("Sensor", back_populates="alarms")
    
    def __repr__(self):
        return f"<AlarmEvent(id={self.id}, sensor_id={self.sensor_id}, parameter='{self.parameter}', status='{self.status}')>"