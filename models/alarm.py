# models/alarm.py
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class AlarmEvent(Base):
    __tablename__ = "alarm_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    parameter = Column(String(50), nullable=False)
    actual_value = Column(Float)
    threshold_min = Column(Float)
    threshold_max = Column(Float)
    status = Column(String(20), nullable=False)

    # Relationship
    sensor = relationship("Sensor", back_populates="alarms")

    def get_severity(self):
        """Determine severity based on status"""
        critical_statuses = ['OVER_VOLTAGE', 'UNDER_VOLTAGE', 'OVER_CURRENT', 'OVER_LIMIT']
        warning_statuses = ['UNDER_CURRENT', 'LOW_PF', 'WARNING']
        
        if self.status.upper() in critical_statuses:
            return 'critical'
        elif self.status.upper() in warning_statuses:
            return 'warning'
        else:
            return 'normal'
    
    def get_status_display(self):
        """Get human-readable status"""
        status_map = {
            'OVER_VOLTAGE': 'Over Voltage',
            'UNDER_VOLTAGE': 'Under Voltage',
            'OVER_CURRENT': 'Over Current',
            'UNDER_CURRENT': 'Under Current',
            'LOW_PF': 'Low PF',
            'NORMAL': 'Normal',
            'WARNING': 'Warning',
            'OVER_LIMIT': 'Over Limit'
        }
        return status_map.get(self.status.upper(), self.status)

    def to_dict(self):
        return {
            "id": self.id,
            "sensor_id": self.sensor_id,
            "timestamp": self.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            "parameter": self.parameter,
            "phase": self.sensor.phase if self.sensor else None,
            "actual_value": float(self.actual_value) if self.actual_value else 0,
            "threshold_min": float(self.threshold_min) if self.threshold_min else None,
            "threshold_max": float(self.threshold_max) if self.threshold_max else None,
            "status": self.get_status_display(),
            "severity": self.get_severity()
        }

    def __repr__(self):
        return f"<AlarmEvent sensor={self.sensor_id} {self.parameter} {self.status}>"