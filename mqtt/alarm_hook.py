# mqtt/alarm_hook.py
"""
Hook AlarmService ke MQTT pipeline.

Dipanggil dari AggregationBuffer.flush_matured_buckets() — HANYA saat
bucket sudah matang (data final), bukan setiap intermediate save.

`reading` bisa berupa SQLAlchemy SensorReading object ATAU plain dict.
Plain dict digunakan karena SQLAlchemy object menjadi detached setelah
session.close() dipanggil di save_sensor_reading().
"""
import logging
from services.alarm_service import AlarmService
from services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class _ReadingProxy:
    """
    Wrapper ringan agar AlarmService bisa akses reading.voltage,
    reading.current, dll — baik dari SQLAlchemy object maupun plain dict.
    """
    __slots__ = ('sensor_id', 'timestamp', 'voltage', 'current',
                 'power', 'energy', 'frequency', 'power_factor',
                 'peak_voltage', 'peak_current')

    def __init__(self, source):
        if isinstance(source, dict):
            for attr in self.__slots__:
                setattr(self, attr, source.get(attr))
        else:
            # SQLAlchemy object — akses atribut langsung
            for attr in self.__slots__:
                setattr(self, attr, getattr(source, attr, None))


def run_alarm_check(db_session, sensor_id: int, reading) -> None:
    """
    Wrapper alarm check untuk MQTT pipeline.

    Args:
        db_session : SQLAlchemy session aktif (bukan session dari save_sensor_reading)
        sensor_id  : ID sensor
        reading    : SensorReading object ATAU plain dict dari save_sensor_reading()
    """
    try:
        proxy = _ReadingProxy(reading)
        alarm_svc = AlarmService(db_session)
        new_events = alarm_svc.check_and_record(sensor_id, proxy)

        if new_events:
            NotificationService.push_many(new_events)

    except Exception as e:
        logger.error(f"Alarm check failed for sensor {sensor_id}: {e}", exc_info=True)