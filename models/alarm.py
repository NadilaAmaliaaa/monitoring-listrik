from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from database import Base


class AlarmEvent(Base):
    __tablename__ = "alarm_events"

    id = Column(Integer, primary_key=True)

    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    # Parameter that triggered alarm
    parameter = Column(String(50), nullable=False)   # voltage, current, power, frequency

    # Snapshot values at alarm time
    actual_value = Column(Float, nullable=False)
    threshold_min = Column(Float)
    threshold_max = Column(Float)

    # Status
    status = Column(String(20), nullable=False)      # LOW, HIGH, NORMAL

    sensor = relationship("Sensor", back_populates="alarms")

    __table_args__ = (
        Index("idx_alarm_sensor_time", "sensor_id", "timestamp"),
        Index("idx_alarm_status", "status"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "sensor_id": self.sensor_id,
            "timestamp": self.timestamp.isoformat(),
            "parameter": self.parameter,
            "actual_value": self.actual_value,
            "threshold_min": self.threshold_min,
            "threshold_max": self.threshold_max,
            "status": self.status
        }

    def __repr__(self):
        return f"<AlarmEvent sensor={self.sensor_id} {self.parameter} {self.status}>"
