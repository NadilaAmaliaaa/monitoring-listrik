# mqtt/alarm_hook.py
"""
Hook AlarmService ke MQTT pipeline.

Cara pakai — tambahkan import dan panggil `run_alarm_check()` di mqtt/client.py
di tempat agregat SensorReading disimpan ke DB.

Cari fungsi yang melakukan db_session.commit() setelah menyimpan SensorReading,
lalu tambahkan dua baris di bawahnya.
"""
import logging
from services.alarm_service import AlarmService
from services.notification_service import NotificationService

logger = logging.getLogger(__name__)


def run_alarm_check(db_session, sensor_id: int, reading) -> None:
    """
    Satu fungsi wrapper agar mqtt/client.py tidak perlu import banyak hal.

    Tambahkan pemanggilan ini di mqtt/client.py setelah SensorReading tersimpan:

        # ── ALARM CHECK ──────────────────────────────────────
        from mqtt.alarm_hook import run_alarm_check
        run_alarm_check(db_session, sensor_id, reading)
        # ─────────────────────────────────────────────────────

    Args:
        db_session : SQLAlchemy session yang sama dengan yang dipakai menyimpan reading
        sensor_id  : ID sensor yang baru menyimpan agregat
        reading    : SensorReading object yang sudah di-commit
    """
    try:
        alarm_svc = AlarmService(db_session)
        new_events = alarm_svc.check_and_record(sensor_id, reading)

        if new_events:
            NotificationService.push_many(new_events)

    except Exception as e:
        # Jangan sampai error alarm menghentikan pipeline MQTT
        logger.error(f"Alarm check failed for sensor {sensor_id}: {e}", exc_info=True)