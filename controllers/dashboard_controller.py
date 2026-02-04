from datetime import datetime, timedelta
from sqlalchemy import func
from database import db
from models.data import Sensor, SensorReading
from mqtt.realtime_store import get_all, get_by_building


class DashboardController:
    def __init__(self, session, building_id=None, building_code=None):
        self.db = session
        self.building_id = building_id
        self.building_code = building_code
    
    def _get_base_query_filter(self, query):
        """Apply building filter to query"""
        if self.building_id:
            query = query.filter(Sensor.building_id == self.building_id)
        return query
        
    def get_voltage(self):
        if not self.building_code:
            return {"R": 0, "S": 0, "T": 0}

        data = get_by_building(self.building_code)

        return {
            "R": round(data.get("R", {}).get("voltage", 0), 2),
            "S": round(data.get("S", {}).get("voltage", 0), 2),
            "T": round(data.get("T", {}).get("voltage", 0), 2),
            "timestamp": (
                data.get("R", {}).get("timestamp")
                or data.get("S", {}).get("timestamp")
                or data.get("T", {}).get("timestamp")
            )
        }

    def get_current(self):
        if not self.building_code:
            return {"R": 0, "S": 0, "T": 0}

        data = get_by_building(self.building_code)
        
        return {
            "R": round(data.get("R", {}).get("current", 0), 2),
            "S": round(data.get("S", {}).get("current", 0), 2),
            "T": round(data.get("T", {}).get("current", 0), 2),
            "timestamp": (
                data.get("R", {}).get("timestamp")
                or data.get("S", {}).get("timestamp")
                or data.get("T", {}).get("timestamp")
            )
        }

    def get_summary(self):
        if not self.db:
            return {"error": "Database session required"}
            
        start_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0)

        query = (
            self.db.query(
                func.avg(SensorReading.frequency).label("freq_avg"),
                func.sum(SensorReading.power).label("power_sum"),
                func.sum(SensorReading.energy).label("energy_sum"),
            )
            .join(Sensor, Sensor.id == SensorReading.sensor_id)
            .filter(SensorReading.timestamp >= start_month)
        )

        query = self._get_base_query_filter(query)
        rows = query.one()

        if not rows or rows.energy_sum is None:
            return {
                "frequency": 0,
                "power": 0,
                "energy": 0
            }

        return {
            "frequency": round(rows.freq_avg or 0, 2),
            "power": round(rows.power_sum or 0, 2),
            "energy": round(rows.energy_sum or 0, 4)
        }
    
    def get_monthly_power_factor(self):
        if not self.db:
            return {"error": "Database session required"}

        start_month = datetime.utcnow().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

        query = (
            self.db.query(
                Sensor.phase,
                func.avg(SensorReading.power_factor).label("pf_avg")
            )
            .join(Sensor, Sensor.id == SensorReading.sensor_id)
            .filter(SensorReading.timestamp >= start_month)
        )

        query = self._get_base_query_filter(query)

        rows = (
            query
            .group_by(Sensor.phase)
            .order_by(Sensor.phase)
            .all()
        )

        return {
            r.phase: round(r.pf_avg or 0, 4)
            for r in rows
        }

    def get_24h_statistics(self):
        if not self.db:
            return {"error": "Database session required"}

        since = datetime.utcnow() - timedelta(hours=24)

        query = (
            self.db.query(
                Sensor.phase,
                func.min(SensorReading.voltage),
                func.max(SensorReading.peak_voltage),
                func.avg(SensorReading.voltage),
                func.min(SensorReading.current),
                func.max(SensorReading.peak_current),
                func.avg(SensorReading.current),
            )
            .join(Sensor, Sensor.id == SensorReading.sensor_id)
            .filter(SensorReading.timestamp >= since)
        )

        query = self._get_base_query_filter(query)

        stats = (
            query
            .group_by(Sensor.phase)
            .order_by(Sensor.phase)
            .all()
        )

        result = {}

        for s in stats:
            phase = s[0]
            result[phase] = {
                "voltage": {
                    "min": round(s[1] or 0, 2),
                    "max": round(s[2] or 0, 2),
                    "avg": round(s[3] or 0, 2),
                },
                "current": {
                    "min": round(s[4] or 0, 2),
                    "max": round(s[5] or 0, 2),
                    "avg": round(s[6] or 0, 2),
                }
            }

        return result
