# models/alarm.py
from datetime import datetime
from sqlalchemy import Column, Integer, Float, Boolean, DateTime, String, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


class AlarmEvent(Base):
    __tablename__ = "alarm_events"
    __table_args__ = {'extend_existing': True}

    id            = Column(Integer, primary_key=True, autoincrement=True)
    sensor_id     = Column(Integer, ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False)
    timestamp     = Column(DateTime(timezone=True), nullable=False)  # waktu alarm mulai
    parameter     = Column(String(50), nullable=False)               # voltage / current
    actual_value  = Column(Float, nullable=True)                     # nilai saat alarm terjadi
    threshold_min = Column(Float, nullable=True)                     # snapshot min saat alarm
    threshold_max = Column(Float, nullable=True)                     # snapshot max saat alarm
    status        = Column(String(50), nullable=False)               # OVER_VOLTAGE, UNDER_CURRENT, dll
    is_normal   = Column(Boolean, default=False, nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # Relationship
    sensor = relationship("Sensor", back_populates="alarms")

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """True jika alarm masih aktif (belum resolved)."""
        return not self.is_normal

    @property
    def duration_seconds(self) -> int | None:
        """Durasi alarm dalam detik. None jika masih aktif."""
        if self.resolved_at and self.timestamp:
            return int((self.resolved_at - self.timestamp).total_seconds())
        return None

    # ── Helper methods ────────────────────────────────────────────────────────

    def resolve(self, resolved_at: datetime = None):
        """Tandai alarm sebagai resolved. Dipanggil oleh AlarmService."""
        self.is_normal  = True
        self.resolved_at = resolved_at or datetime.utcnow()

    def get_severity(self) -> str:
        """Kembalikan severity string untuk frontend toast."""
        critical = {"OVER_VOLTAGE", "UNDER_VOLTAGE", "OVER_CURRENT"}
        if self.status in critical:
            return "critical"
        if self.status in {"UNDER_CURRENT", "LOW_PF", "OVER_LIMIT", "UNDER_LIMIT"}:
            return "warning"
        return "normal"

    def get_status_display(self) -> str:
        """Label human-readable untuk status."""
        labels = {
            "OVER_VOLTAGE":  "Tegangan Terlalu Tinggi",
            "UNDER_VOLTAGE": "Tegangan Terlalu Rendah",
            "OVER_CURRENT":  "Arus Terlalu Tinggi",
            "UNDER_CURRENT": "Arus Terlalu Rendah",
            "OVER_LIMIT":    "Frekuensi Terlalu Tinggi",
            "UNDER_LIMIT":   "Frekuensi Terlalu Rendah",
            "LOW_PF":        "Power Factor Rendah",
            "NORMAL":        "Normal",
        }
        return labels.get(self.status, self.status)

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "sensor_id":     self.sensor_id,
            "phase":         self.sensor.phase if self.sensor else None,
            "timestamp":     self.timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.timestamp else None,
            "parameter":     self.parameter,
            "actual_value":  self.actual_value,
            "threshold_min": self.threshold_min,
            "threshold_max": self.threshold_max,
            "status":        self.status,
            "status_display": self.get_status_display(),
            "severity":      self.get_severity(),
            "is_normal":     self.is_normal,
            "resolved_at":   self.resolved_at.strftime('%Y-%m-%d %H:%M:%S') if self.resolved_at else None,
            "duration_seconds": self.duration_seconds,
        }

    def __repr__(self):
        state = "resolved" if self.is_normal else "ACTIVE"
        return f"<AlarmEvent sensor={self.sensor_id} {self.parameter}={self.status} [{state}]>"