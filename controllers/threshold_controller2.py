# controllers/threshold_controller.py
import statistics
from models.threshold2 import SensorThreshold
from models.data import Sensor, SensorReading


DEFAULT_THRESHOLD = {
    "voltage_min": 180.0,
    "voltage_max": 240.0,
    "voltage_min_enabled": True,
    "voltage_max_enabled": True,
    "current_min": 0.5,
    "current_max": 32.0,
    "current_min_enabled": False,
    "current_max_enabled": True,
    "auto_threshold_enabled": False,
}

SAFETY_BOUNDS = {
    "voltage": {"min": 100.0, "max": 300.0},
    "current": {"min": 0.0,   "max": 100.0},
}


class ThresholdController:
    def __init__(self, session, building_id=None):
        self.session = session
        self.building_id = building_id

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_sensors_in_building(self):
        if not self.building_id:
            return []
        return (
            self.session.query(Sensor)
            .filter(Sensor.building_id == self.building_id)
            .all()
        )

    def _sensor_belongs_to_building(self, sensor_id: int) -> bool:
        if not self.building_id:
            return True
        sensor = self.session.query(Sensor).get(sensor_id)
        return sensor is not None and sensor.building_id == self.building_id

    def _get_or_create(self, sensor_id: int):
        threshold = (
            self.session.query(SensorThreshold)
            .filter(SensorThreshold.sensor_id == sensor_id)
            .first()
        )
        if not threshold:
            threshold = self._create_default(sensor_id)
        return threshold

    def _create_default(self, sensor_id: int):
        threshold = SensorThreshold(sensor_id=sensor_id, **DEFAULT_THRESHOLD)
        self.session.add(threshold)
        self.session.commit()
        self.session.refresh(threshold)
        return threshold

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_all_settings(self):
        """Get threshold untuk semua sensor di building aktif."""
        sensors = self._get_sensors_in_building()
        return [self._get_or_create(s.id) for s in sensors]

    def get_settings_by_sensor(self, sensor_id: int):
        if not self._sensor_belongs_to_building(sensor_id):
            return None
        return self._get_or_create(sensor_id)

    def get_building_auto_state(self):
        """
        Kembalikan state auto threshold untuk building aktif.
        True hanya jika SEMUA sensor di building mengaktifkan auto.
        Dipakai untuk sinkronisasi state toggle di UI.
        """
        sensors = self._get_sensors_in_building()
        if not sensors:
            return False
        thresholds = [self._get_or_create(s.id) for s in sensors]
        return all(t.auto_threshold_enabled for t in thresholds)

    # ── Write Manual (mutual exclusive) ───────────────────────────────────────

    def update_settings(self, sensor_id: int, data: dict):
        """
        Update threshold manual untuk sensor tertentu.
        Otomatis menonaktifkan auto_threshold_enabled karena user memilih manual.
        Returns (SensorThreshold, error_message).
        """
        if not self._sensor_belongs_to_building(sensor_id):
            return None, "Sensor tidak termasuk dalam building aktif."

        error = self._validate(data)
        if error:
            return None, error

        threshold = self._get_or_create(sensor_id)

        # Simpan nilai manual dan matikan auto mode
        updatable_fields = [
            "voltage_min", "voltage_max", "voltage_min_enabled", "voltage_max_enabled",
            "current_min", "current_max", "current_min_enabled", "current_max_enabled",
        ]
        for field in updatable_fields:
            if field in data:
                setattr(threshold, field, data[field])

        # Mutual exclusive: manual save → auto OFF
        threshold.auto_threshold_enabled = False

        self.session.commit()
        self.session.refresh(threshold)
        return threshold, None

    def reset_to_defaults(self, sensor_id: int):
        """Reset ke factory defaults dan matikan auto mode."""
        if not self._sensor_belongs_to_building(sensor_id):
            return None, "Sensor tidak termasuk dalam building aktif."

        threshold = self._get_or_create(sensor_id)
        for field, value in DEFAULT_THRESHOLD.items():
            setattr(threshold, field, value)  # DEFAULT_THRESHOLD sudah include auto_threshold_enabled=False

        self.session.commit()
        self.session.refresh(threshold)
        return threshold, None

    # ── Toggle Auto Mode ──────────────────────────────────────────────────────

    def set_auto_mode(self, sensor_id: int, enabled: bool):
        """
        Aktifkan atau nonaktifkan auto threshold untuk sensor tertentu.
        Jika enabled=True, langsung kalkulasi dan terapkan IQR dari historis.
        Jika enabled=False, nilai threshold tetap, tapi mode kembali ke manual.
        Returns (SensorThreshold, preview, error_message).
        """
        if not self._sensor_belongs_to_building(sensor_id):
            return None, None, "Sensor tidak termasuk dalam building aktif."

        threshold = self._get_or_create(sensor_id)

        if not enabled:
            # Nonaktifkan auto → kembali ke manual, nilai threshold tidak diubah
            threshold.auto_threshold_enabled = False
            self.session.commit()
            self.session.refresh(threshold)
            return threshold, None, None

        # Aktifkan auto → kalkulasi IQR dan terapkan sekaligus
        threshold, preview, error = self.apply_auto_threshold(sensor_id)
        return threshold, preview, error

    def set_auto_mode_all(self, enabled: bool, days: int = 30):
        """
        Aktifkan atau nonaktifkan auto threshold untuk SEMUA sensor di building aktif.
        Dipanggil saat user klik toggle global di banner.
        Returns list of { sensor_id, phase, threshold, preview, error }.
        """
        sensors = self._get_sensors_in_building()
        results = []

        for sensor in sensors:
            if enabled:
                threshold, preview, error = self.apply_auto_threshold(sensor.id, days=days)
            else:
                threshold = self._get_or_create(sensor.id)
                threshold.auto_threshold_enabled = False
                self.session.commit()
                self.session.refresh(threshold)
                preview, error = None, None

            results.append({
                "sensor_id": sensor.id,
                "phase": sensor.phase,
                "threshold": threshold.to_dict() if threshold else None,
                "preview": preview,
                "error": error,
            })

        return results

    # ── Auto Threshold (IQR) ──────────────────────────────────────────────────

    def calculate_auto_threshold(self, sensor_id: int, days: int = 30):
        """
        Hitung threshold dari historis menggunakan IQR (Tukey's fences).
        TIDAK menyimpan ke DB — hanya kalkulasi untuk preview.
        Returns (calc_dict, error_message).
        """
        from datetime import datetime, timedelta

        if not self._sensor_belongs_to_building(sensor_id):
            return None, "Sensor tidak termasuk dalam building aktif."

        cutoff = datetime.utcnow() - timedelta(days=days)
        readings = (
            self.session.query(SensorReading)
            .filter(
                SensorReading.sensor_id == sensor_id,
                SensorReading.timestamp >= cutoff,
            )
            .all()
        )

        if len(readings) < 10:
            return None, f"Data historis tidak cukup. Minimal 10 data diperlukan, saat ini hanya {len(readings)} data."

        voltage_values = [r.voltage for r in readings if r.voltage is not None]
        current_values = [r.current for r in readings if r.current is not None]
        result = {}

        if len(voltage_values) >= 10:
            v_min, v_max = self._iqr_bounds(voltage_values)
            v_min = max(v_min, SAFETY_BOUNDS["voltage"]["min"])
            v_max = min(v_max, SAFETY_BOUNDS["voltage"]["max"])
            result["voltage"] = {
                "threshold_min": round(v_min, 2),
                "threshold_max": round(v_max, 2),
                "data_points": len(voltage_values),
                "mean": round(statistics.mean(voltage_values), 2),
                "stdev": round(statistics.stdev(voltage_values), 2),
            }

        if len(current_values) >= 10:
            a_min, a_max = self._iqr_bounds(current_values)
            a_min = max(a_min, SAFETY_BOUNDS["current"]["min"])
            a_max = min(a_max, SAFETY_BOUNDS["current"]["max"])
            result["current"] = {
                "threshold_min": round(a_min, 2),
                "threshold_max": round(a_max, 2),
                "data_points": len(current_values),
                "mean": round(statistics.mean(current_values), 2),
                "stdev": round(statistics.stdev(current_values), 2),
            }

        if not result:
            return None, "Tidak ada data voltage atau current yang cukup untuk kalkulasi."

        return result, None

    def apply_auto_threshold(self, sensor_id: int, days: int = 30):
        """
        Hitung dan simpan threshold otomatis, lalu set auto_threshold_enabled=True.
        Mutual exclusive: auto ON → manual input dikunci di sisi UI.
        Returns (SensorThreshold, preview_dict, error_message).
        """
        calc, error = self.calculate_auto_threshold(sensor_id, days)
        if error:
            return None, None, error

        threshold = self._get_or_create(sensor_id)

        if "voltage" in calc:
            threshold.voltage_min = calc["voltage"]["threshold_min"]
            threshold.voltage_max = calc["voltage"]["threshold_max"]
            threshold.voltage_min_enabled = True
            threshold.voltage_max_enabled = True

        if "current" in calc:
            threshold.current_min = calc["current"]["threshold_min"]
            threshold.current_max = calc["current"]["threshold_max"]
            threshold.current_max_enabled = True

        # Mutual exclusive: auto ON → nonaktifkan kemampuan edit manual
        threshold.auto_threshold_enabled = True

        self.session.commit()
        self.session.refresh(threshold)
        return threshold, calc, None

    def apply_auto_threshold_all(self, days: int = 30):
        """Terapkan auto threshold ke semua sensor di building aktif."""
        sensors = self._get_sensors_in_building()
        results = []
        for sensor in sensors:
            threshold, preview, error = self.apply_auto_threshold(sensor.id, days)
            results.append({
                "sensor_id": sensor.id,
                "phase": sensor.phase,
                "threshold": threshold.to_dict() if threshold else None,
                "preview": preview,
                "error": error,
            })
        return results

    # ── IQR ───────────────────────────────────────────────────────────────────

    @staticmethod
    def _iqr_bounds(values: list, multiplier: float = 1.5):
        sorted_vals = sorted(values)
        q1 = ThresholdController._percentile(sorted_vals, 25)
        q3 = ThresholdController._percentile(sorted_vals, 75)
        iqr = q3 - q1
        return q1 - multiplier * iqr, q3 + multiplier * iqr

    @staticmethod
    def _percentile(sorted_data: list, percent: float):
        n = len(sorted_data)
        if n == 0:
            return 0
        k = (n - 1) * percent / 100
        f = int(k)
        c = f + 1
        if c >= n:
            return sorted_data[f]
        return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])

    # ── Threshold Checkers ────────────────────────────────────────────────────

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
        """Check voltage dan current. Returns list siap disimpan ke AlarmEvent."""
        v_status, v_min, v_max = self.check_voltage(sensor_id, voltage)
        a_status, a_min, a_max = self.check_current(sensor_id, current)
        return [
            {"parameter": "voltage", "actual_value": voltage,
             "status": v_status, "threshold_min": v_min, "threshold_max": v_max},
            {"parameter": "current", "actual_value": current,
             "status": a_status, "threshold_min": a_min, "threshold_max": a_max},
        ]

    # ── Validation ────────────────────────────────────────────────────────────

    @staticmethod
    def _validate(data: dict):
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