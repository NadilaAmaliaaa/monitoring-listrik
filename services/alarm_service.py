# services/alarm_service.py
"""
AlarmService — dipanggil setiap kali SensorReading agregat tersimpan (1 menit).

State machine dengan single-row lifecycle:

    Kondisi sebelumnya | Kondisi baru | Aksi
    ─────────────────────────────────────────────────────────────────
    NORMAL (no row)    | ABNORMAL     | INSERT row baru (is_normal=False)
    ABNORMAL (active)  | NORMAL       | UPDATE row (is_normal=True, resolved_at=now)
    ABNORMAL (active)  | ABNORMAL     | skip — tidak ada perubahan
    NORMAL (resolved)  | NORMAL       | skip
    NORMAL (resolved)  | ABNORMAL     | INSERT row baru (alarm baru)

Keuntungan:
    - 1 alarm = 1 row (bukan 2)
    - duration otomatis terhitung dari timestamp dan resolved_at
    - query "alarm aktif" cukup: WHERE is_normal=False
"""
import logging
from datetime import datetime, timezone
from models.alarm import AlarmEvent
from models.threshold2 import SensorThreshold

logger = logging.getLogger(__name__)


class AlarmService:
    def __init__(self, session):
        self.session = session

    # ── Entry point ───────────────────────────────────────────────────────────

    def check_and_record(self, sensor_id: int, reading) -> list:
        """
        Cek SensorReading terhadap threshold aktif.

        Returns:
            list — AlarmEvent yang baru di-INSERT atau di-UPDATE.
                   Kosong [] jika tidak ada perubahan state.
        """
        threshold = (
            self.session.query(SensorThreshold)
            .filter(SensorThreshold.sensor_id == sensor_id)
            .first()
        )
        if not threshold:
            logger.debug(f"No threshold for sensor {sensor_id}, skipping")
            return []

        changed = []

        if reading.voltage is not None:
            event = self._evaluate(
                sensor_id=sensor_id,
                parameter="voltage",
                actual_value=reading.voltage,
                threshold_min=threshold.voltage_min if threshold.voltage_min_enabled else None,
                threshold_max=threshold.voltage_max if threshold.voltage_max_enabled else None,
            )
            if event:
                changed.append(event)

        if reading.current is not None:
            event = self._evaluate(
                sensor_id=sensor_id,
                parameter="current",
                actual_value=reading.current,
                threshold_min=threshold.current_min if threshold.current_min_enabled else None,
                threshold_max=threshold.current_max if threshold.current_max_enabled else None,
            )
            if event:
                changed.append(event)

        if changed:
            logger.info(
                f"Sensor {sensor_id}: {len(changed)} alarm state change(s) — "
                + ", ".join(
                    f"{e.parameter}:{e.status}"
                    + (" [resolved]" if e.is_normal else " [active]")
                    for e in changed
                )
            )

        return changed

    # ── Core state machine ────────────────────────────────────────────────────

    def _evaluate(self, sensor_id, parameter, actual_value,
                  threshold_min, threshold_max) -> AlarmEvent | None:
        """
        Tentukan status baru dan jalankan state machine.

        - Jika status baru = NORMAL dan ada alarm aktif → resolve (UPDATE)
        - Jika status baru = ABNORMAL dan tidak ada alarm aktif → INSERT baru
        - Selain itu → skip
        """
        new_status = self._determine_status(parameter, actual_value, threshold_min, threshold_max)
        is_abnormal = new_status != "NORMAL"

        # Cari alarm terakhir yang masih aktif untuk sensor+parameter ini
        active_alarm = self._get_active_alarm(sensor_id, parameter)

        if is_abnormal and active_alarm is None:
            # NORMAL → ABNORMAL : INSERT alarm baru
            event = AlarmEvent(
                sensor_id=sensor_id,
                timestamp=datetime.now(timezone.utc),
                parameter=parameter,
                actual_value=actual_value,
                threshold_min=threshold_min,
                threshold_max=threshold_max,
                status=new_status,
                is_normal=False,
                resolved_at=None,
            )
            self.session.add(event)
            self.session.commit()
            self.session.refresh(event)

            logger.info(
                f"AlarmEvent INSERT: sensor={sensor_id} {parameter} "
                f"NORMAL → {new_status} (value={actual_value})"
            )
            return event

        elif not is_abnormal and active_alarm is not None:
            # ABNORMAL → NORMAL : UPDATE row yang sama (resolve)
            active_alarm.resolve(resolved_at=datetime.now(timezone.utc))
            self.session.commit()
            self.session.refresh(active_alarm)

            logger.info(
                f"AlarmEvent RESOLVED: sensor={sensor_id} {parameter} "
                f"{active_alarm.status} → NORMAL "
                f"(duration={active_alarm.duration_seconds}s)"
            )
            return active_alarm

        # Tidak ada perubahan state — skip
        return None

    def _determine_status(self, parameter, value, threshold_min, threshold_max) -> str:
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

    def _get_active_alarm(self, sensor_id: int, parameter: str) -> AlarmEvent | None:
        """
        Ambil alarm terakhir yang masih aktif (is_normal=False).
        None jika tidak ada alarm aktif untuk sensor+parameter ini.
        """
        return (
            self.session.query(AlarmEvent)
            .filter(
                AlarmEvent.sensor_id == sensor_id,
                AlarmEvent.parameter == parameter,
                AlarmEvent.is_normal == False,
            )
            .order_by(AlarmEvent.timestamp.desc())
            .first()
        )