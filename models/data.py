from datetime import datetime
from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship
from database import db


class Sensor(db.Model):
    __tablename__ = "sensors"

    id = Column(Integer, primary_key=True)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=False)
    name = Column(String(100), nullable=False)
    phase = Column(String(1), nullable=False)

    building = relationship("Building", back_populates="sensors")
    readings = relationship("SensorReading", back_populates="sensor")
    thresholds = relationship("SensorThreshold", back_populates="sensor")
    alarms = relationship("AlarmEvent", back_populates="sensor")


class SensorReading(db.Model):
    __tablename__ = "sensor_readings"

    # Composite primary key sesuai ERD
    sensor_id = Column(Integer, ForeignKey("sensors.id"), primary_key=True)
    timestamp = Column(DateTime, primary_key=True, default=datetime.utcnow)

    voltage = Column(Float, nullable=False)
    current = Column(Float, nullable=False)
    power = Column(Float, nullable=False)
    frequency = Column(Float, nullable=False)
    power_factor = Column(Float, nullable=False)
    energy = Column(Float, nullable=False)

    peak_voltage = Column(Float)
    peak_current = Column(Float)

    sensor = relationship("Sensor", back_populates="readings")
    
    __table_args__ = (
        db.Index("idx_sensor_time", "sensor_id", "timestamp"),
        db.Index("idx_time", "timestamp"),
    )


class SensorThreshold(db.Model):
    __tablename__ = "sensor_thresholds"

    id = Column(Integer, primary_key=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=False)

    voltage_min = Column(Float)
    voltage_max = Column(Float)
    current_min = Column(Float)
    current_max = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

    sensor = relationship("Sensor", back_populates="thresholds")


class AlarmEvent(db.Model):
    __tablename__ = "alarm_events"

    id = Column(Integer, primary_key=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=False)

    timestamp = Column(DateTime, default=datetime.utcnow)
    parameter = Column(String(50))  # voltage / current / power
    actual_value = Column(Float)
    threshold_min = Column(Float)
    threshold_max = Column(Float)
    status = Column(String(20))  # LOW / HIGH / NORMAL

    sensor = relationship("Sensor", back_populates="alarms")
    
    def __repr__(self):
        return f"<AlarmEvent(sensor_id={self.sensor_id}, parameter={self.parameter}, status={self.status}, timestamp={self.timestamp})>"