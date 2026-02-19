# services/alarm_service.py
"""
AlarmService — dipanggil oleh MQTT client setiap kali SensorReading agregat tersimpan.

State machine (mencegah spam AlarmEvent):
    NORMAL → OVER_VOLTAGE       ✅ simpan event + push notifikasi
    OVER_VOLTAGE → NORMAL       ✅ simpan event (resolved) + push notifikasi
    OVER_VOLTAGE → OVER_VOLTAGE ❌ skip — tidak ada perubahan
"""
import logging
from datetime import datetime
from models.alarm import AlarmEvent
from models.threshold2 import SensorThreshold  # sesuai naming di app.py

logger = logging.getLogger(__name__)


class AlarmService:
    def __init__(self, session):
        self.session = session

    # ── Entry point ───────────────────────────────────────────────────────────

    def check_and_record(self, sensor_id: int, reading) -> list:
        """
        Cek SensorReading terhadap threshold aktif.
        Simpan AlarmEvent HANYA jika status berubah dari event terakhir.

        Args:
            sensor_id : ID sensor
            reading   : SensorReading object yang baru tersimpan (harus sudah commit)

        Returns:
            list[AlarmEvent] — event baru yang tersimpan, bisa []
        """
        threshold = (
            self.session.query(SensorThreshold)
            .filter(SensorThreshold.sensor_id == sensor_id)
            .first()
        )
        if not threshold:
            logger.debug(f"No threshold for sensor {sensor_id}, skipping")
            return []

        new_events = []

        if reading.voltage is not None:
            event = self._evaluate_and_record(
                sensor_id=sensor_id,
                parameter="voltage",
                actual_value=reading.voltage,
                threshold_min=threshold.voltage_min if threshold.voltage_min_enabled else None,
                threshold_max=threshold.voltage_max if threshold.voltage_max_enabled else None,
            )
            if event:
                new_events.append(event)

        if reading.current is not None:
            event = self._evaluate_and_record(
                sensor_id=sensor_id,
                parameter="current",
                actual_value=reading.current,
                threshold_min=threshold.current_min if threshold.current_min_enabled else None,
                threshold_max=threshold.current_max if threshold.current_max_enabled else None,
            )
            if event:
                new_events.append(event)

        if new_events:
            logger.info(
                f"Sensor {sensor_id}: {len(new_events)} alarm event(s) — "
                + ", ".join(f"{e.parameter}:{e.status}" for e in new_events)
            )

        return new_events

    # ── State machine ─────────────────────────────────────────────────────────

    def _evaluate_and_record(self, sensor_id, parameter, actual_value,
                              threshold_min, threshold_max):
        new_status  = self._determine_status(parameter, actual_value, threshold_min, threshold_max)
        last_status = self._get_last_status(sensor_id, parameter)

        if new_status == last_status:
            return None  # tidak ada perubahan state — skip

        event = AlarmEvent(
            sensor_id=sensor_id,
            timestamp=datetime.utcnow(),
            parameter=parameter,
            actual_value=actual_value,
            threshold_min=threshold_min,
            threshold_max=threshold_max,
            status=new_status,
        )
        self.session.add(event)
        self.session.commit()
        self.session.refresh(event)

        logger.info(
            f"AlarmEvent: sensor={sensor_id} {parameter} "
            f"[{last_status} → {new_status}] value={actual_value}"
        )
        return event

    def _determine_status(self, parameter, value, threshold_min, threshold_max):
        if parameter == "voltage":
            if threshold_max is not None and value > threshold_max:
                return "OVER_VOLTAGE"
            if threshold_min is not None and value < threshold_min:
                return "UNDER_VOLTAGE"
        elif parameter == "current":
            if threshold_max is not None and value > threshold_max:
                return "OVER_CURRENT"
            if threshold_min is not None and value < threshold_min:
                return "UNDER_CURRENT"
        elif parameter == "frequency":
            if threshold_max is not None and value > threshold_max:
                return "OVER_LIMIT"
            if threshold_min is not None and value < threshold_min:
                return "UNDER_LIMIT"
        elif parameter == "power_factor":
            if threshold_min is not None and value < threshold_min:
                return "LOW_PF"
        return "NORMAL"

    def _get_last_status(self, sensor_id, parameter):
        """Ambil status terakhir dari DB. Default NORMAL jika belum ada riwayat."""
        last = (
            self.session.query(AlarmEvent)
            .filter(
                AlarmEvent.sensor_id == sensor_id,
                AlarmEvent.parameter == parameter,
            )
            .order_by(AlarmEvent.timestamp.desc())
            .first()
        )
        return last.status if last else "NORMAL"