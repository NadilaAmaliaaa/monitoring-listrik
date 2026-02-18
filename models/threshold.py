# models/threshold.py
from datetime import datetime
from sqlalchemy import Column, Integer, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class SensorThreshold(Base):
    __tablename__ = "sensor_thresholds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Voltage thresholds (Volt)
    voltage_min = Column(Float, nullable=True)
    voltage_max = Column(Float, nullable=True)
    voltage_min_enabled = Column(Boolean, default=True)
    voltage_max_enabled = Column(Boolean, default=True)

    # Current thresholds (Ampere)
    current_min = Column(Float, nullable=True)
    current_max = Column(Float, nullable=True)
    current_min_enabled = Column(Boolean, default=False)
    current_max_enabled = Column(Boolean, default=True)  # Note: typo 'current_mac_enabled' di DDL, pakai nama benar di ORM

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Relationship
    sensor = relationship("Sensor", back_populates="thresholds")

    def to_dict(self):
        return {
            "id": self.id,
            "sensor_id": self.sensor_id,
            "voltage_min": self.voltage_min,
            "voltage_max": self.voltage_max,
            "voltage_min_enabled": self.voltage_min_enabled,
            "voltage_max_enabled": self.voltage_max_enabled,
            "current_min": self.current_min,
            "current_max": self.current_max,
            "current_min_enabled": self.current_min_enabled,
            "current_max_enabled": self.current_max_enabled,
            "created_at": self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }

    def __repr__(self):
        return f"<SensorThreshold sensor={self.sensor_id} V:{self.voltage_min}-{self.voltage_max} A:{self.current_min}-{self.current_max}>"