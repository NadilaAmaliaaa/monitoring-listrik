from datetime import datetime, timedelta
from sqlalchemy import func
from database import db
from models.data import Sensor, SensorReading
from mqtt.realtime_store import get_all


class DashboardController:
    def __init__(self, session):
        self.db = session
        
    def get_voltage(self):
        data = get_all()
        return {
            "R": round(data["R"]["voltage"], 2),
            "S": round(data["S"]["voltage"], 2),
            "T": round(data["T"]["voltage"], 2),
            "timestamp": data["R"]["timestamp"]
        }

    def get_current(self):
        data = get_all()
        return {
            "R": round(data["R"]["current"], 2),
            "S": round(data["S"]["current"], 2),
            "T": round(data["T"]["current"], 2),
            "timestamp": data["R"]["timestamp"]
        }

    def get_summary(self):
        start_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0)

        rows = (
            self.db.query(
                func.avg(SensorReading.frequency).label("freq_avg"),
                func.sum(SensorReading.power).label("power_sum"),
                func.sum(SensorReading.energy).label("energy_sum"),
            )
            .filter(SensorReading.timestamp >= start_month)
            .one()
        )

        if rows.energy_sum is None:
            return {
                "frequency": 0,
                "power": 0,
                "energy": 0
            }

        return {
            "frequency": round(rows.freq_avg, 2),
            "power": round(rows.power_sum, 2),
            "energy": round(rows.energy_sum, 4)
        }
    
    def get_monthly_power_factor(self):
        """Rata-rata PF bulan berjalan per phase"""
        start_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0)

        rows = (
            self.db.query(
                Sensor.phase,
                func.avg(SensorReading.power_factor).label("pf_avg")
            )
            .join(Sensor, Sensor.id == SensorReading.sensor_id)
            .filter(SensorReading.timestamp >= start_month)
            .group_by(Sensor.phase)
            .order_by(Sensor.phase)
            .all()
        )

        return {
            r.phase: round(r.pf_avg, 4)
            for r in rows
        }

    def get_24h_statistics(self):
        """Min, Max, Avg Voltage & Current per phase (24 jam)"""
        since = datetime.utcnow() - timedelta(hours=24)

        stats = (
            self.db.query(
                Sensor.phase,
                func.min(SensorReading.voltage),
                func.max(SensorReading.voltage),
                func.avg(SensorReading.voltage),
                func.min(SensorReading.current),
                func.max(SensorReading.current),
                func.avg(SensorReading.current),
            )
            .join(Sensor, Sensor.id == SensorReading.sensor_id)
            .filter(SensorReading.timestamp >= since)
            .group_by(Sensor.phase)
            .order_by(Sensor.phase)
            .all()
        )

        result = {}

        for s in stats:
            phase = s[0]
            result[phase] = {
                "voltage": {
                    "min": round(s[1], 2),
                    "max": round(s[2], 2),
                    "avg": round(s[3], 2),
                },
                "current": {
                    "min": round(s[4], 2),
                    "max": round(s[5], 2),
                    "avg": round(s[6], 2),
                }
            }

        return result
