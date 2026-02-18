# controllers/threshold_controller.py
from models.threshold import SensorThreshold
from models.data import Sensor


DEFAULT_THRESHOLD = {
    "voltage_min": 180.0,
    "voltage_max": 240.0,
    "voltage_min_enabled": True,
    "voltage_max_enabled": True,
    "current_min": 0.5,
    "current_max": 32.0,
    "current_min_enabled": False,
    "current_max_enabled": True,
}


class ThresholdController:
    def __init__(self, session, building_id=None):
        self.session = session
        self.building_id = building_id

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_base_query(self):
        """
        Base query untuk SensorThreshold, di-join ke Sensor.
        Jika building_id aktif, filter hanya sensor milik building tersebut.
        """
        query = (
            self.session.query(SensorThreshold)
            .join(Sensor, SensorThreshold.sensor_id == Sensor.id)
        )
        if self.building_id:
            query = query.filter(Sensor.building_id == self.building_id)
        return query

    def _get_sensors_in_building(self):
        """Get all sensors for the active building."""
        if not self.building_id:
            return []
        return (
            self.session.query(Sensor)
            .filter(Sensor.building_id == self.building_id)
            .all()
        )

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_all_settings(self):
        """
        Get threshold rows for all sensors in the active building.
        Auto-creates default row for any sensor that doesn't have one yet.
        Returns list of SensorThreshold.
        """
        sensors = self._get_sensors_in_building()
        result = []
        for sensor in sensors:
            threshold = self._get_or_create(sensor.id)
            result.append(threshold)
        return result

    def get_settings_by_sensor(self, sensor_id: int):
        """
        Get threshold row for a specific sensor.
        Auto-creates default if not exists.
        Returns SensorThreshold or None if sensor not in active building.
        """
        if not self._sensor_belongs_to_building(sensor_id):
            return None
        return self._get_or_create(sensor_id)

    def _get_or_create(self, sensor_id: int):
        """Get existing threshold row or create default."""
        threshold = (
            self.session.query(SensorThreshold)
            .filter(SensorThreshold.sensor_id == sensor_id)
            .first()
        )
        if not threshold:
            threshold = self._create_default(sensor_id)
        return threshold

    def _create_default(self, sensor_id: int):
        """Create a SensorThreshold row with default values."""
        threshold = SensorThreshold(sensor_id=sensor_id, **DEFAULT_THRESHOLD)
        self.session.add(threshold)
        self.session.commit()
        self.session.refresh(threshold)
        return threshold

    def _sensor_belongs_to_building(self, sensor_id: int) -> bool:
        """Verify sensor belongs to the active building."""
        if not self.building_id:
            return True  # no building filter active
        sensor = self.session.query(Sensor).get(sensor_id)
        return sensor is not None and sensor.building_id == self.building_id

    # ── Write ─────────────────────────────────────────────────────────────────

    def update_settings(self, sensor_id: int, data: dict):
        """
        Update threshold settings for a specific sensor.
        Returns (SensorThreshold, error_message). error_message is None on success.

        Expected data keys (all optional):
            voltage_min, voltage_max, voltage_min_enabled, voltage_max_enabled,
            current_min, current_max, current_min_enabled, current_max_enabled
        """
        if not self._sensor_belongs_to_building(sensor_id):
            return None, "Sensor tidak termasuk dalam building aktif."

        error = self._validate(data)
        if error:
            return None, error

        threshold = self._get_or_create(sensor_id)

        updatable_fields = [
            "voltage_min", "voltage_max", "voltage_min_enabled", "voltage_max_enabled",
            "current_min", "current_max", "current_min_enabled", "current_max_enabled",
        ]
        for field in updatable_fields:
            if field in data:
                setattr(threshold, field, data[field])

        self.session.commit()
        self.session.refresh(threshold)
        return threshold, None

    def reset_to_defaults(self, sensor_id: int):
        """
        Reset threshold settings for a specific sensor to factory defaults.
        Returns (SensorThreshold, error_message).
        """
        if not self._sensor_belongs_to_building(sensor_id):
            return None, "Sensor tidak termasuk dalam building aktif."

        threshold = self._get_or_create(sensor_id)

        for field, value in DEFAULT_THRESHOLD.items():
            setattr(threshold, field, value)

        self.session.commit()
        self.session.refresh(threshold)
        return threshold, None

    # ── Threshold Checkers ────────────────────────────────────────────────────
    # Dipakai pipeline monitoring saat evaluasi data sensor masuk.
    # Hasil status + snapshot min/max langsung disimpan ke AlarmEvent.

    def check_voltage(self, sensor_id: int, value: float):
        """Returns (status, threshold_min, threshold_max)"""
        t = self._get_or_create(sensor_id)
        if t.voltage_max_enabled and t.voltage_max is not None and value > t.voltage_max:
            return "OVER_VOLTAGE", t.voltage_min, t.voltage_max
        if t.voltage_min_enabled and t.voltage_min is not None and value < t.voltage_min:
            return "UNDER_VOLTAGE", t.voltage_min, t.voltage_max
        return "NORMAL", t.voltage_min, t.voltage_max

    def check_current(self, sensor_id: int, value: float):
        """Returns (status, threshold_min, threshold_max)"""
        t = self._get_or_create(sensor_id)
        if t.current_max_enabled and t.current_max is not None and value > t.current_max:
            return "OVER_CURRENT", t.current_min, t.current_max
        if t.current_min_enabled and t.current_min is not None and value < t.current_min:
            return "UNDER_CURRENT", t.current_min, t.current_max
        return "NORMAL", t.current_min, t.current_max

    def check_all(self, sensor_id: int, voltage: float, current: float):
        """
        Check voltage and current for a sensor.
        Returns list siap disimpan ke AlarmEvent:
        [
            {
                "parameter": "voltage",
                "actual_value": 220.0,
                "status": "NORMAL",
                "threshold_min": 180.0,
                "threshold_max": 240.0,
            },
            ...
        ]
        """
        v_status, v_min, v_max = self.check_voltage(sensor_id, voltage)
        a_status, a_min, a_max = self.check_current(sensor_id, current)

        return [
            {
                "parameter": "voltage",
                "actual_value": voltage,
                "status": v_status,
                "threshold_min": v_min,
                "threshold_max": v_max,
            },
            {
                "parameter": "current",
                "actual_value": current,
                "status": a_status,
                "threshold_min": a_min,
                "threshold_max": a_max,
            },
        ]

    # ── Validation ────────────────────────────────────────────────────────────

    @staticmethod
    def _validate(data: dict):
        """Validate threshold data. Returns error string or None."""
        v_min = data.get("voltage_min")
        v_max = data.get("voltage_max")
        a_min = data.get("current_min")
        a_max = data.get("current_max")

        if v_min is not None and v_max is not None:
            if v_min >= v_max:
                return "Voltage minimum harus lebih kecil dari maximum."
            if v_min < 0:
                return "Voltage minimum tidak boleh negatif."

        if a_min is not None and a_max is not None:
            if a_min >= a_max:
                return "Current minimum harus lebih kecil dari maximum."
            if a_min < 0:
                return "Current minimum tidak boleh negatif."

        return None