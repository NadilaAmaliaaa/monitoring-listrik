# services/notification_service.py
"""
NotificationService — push alarm ke browser via SSE.

Mendukung dua jenis push:
    1. Alarm aktif  (is_normal=False) → toast merah/kuning
    2. Alarm resolved (is_normal=True) → toast hijau "Kondisi Kembali Normal"

Kedua jenis menggunakan row AlarmEvent yang SAMA — tidak ada row kedua.
"""
import json
import queue
import threading
import logging

logger = logging.getLogger(__name__)

_subscribers: dict = {}
_lock = threading.Lock()


class NotificationService:

    @staticmethod
    def push(event) -> None:
        """
        Kirim AlarmEvent ke semua SSE subscriber.
        Bekerja untuk alarm baru (is_normal=False) maupun resolved (is_normal=True).
        """
        try:
            # Tentukan apakah ini notif alarm atau resolved
            is_resolved = event.is_normal

            payload = json.dumps({
                "type":          "alarm",
                "id":            event.id,
                "sensor_id":     event.sensor_id,
                "parameter":     event.parameter,
                "phase":         event.sensor.phase if event.sensor else None,
                "actual_value":  float(event.actual_value) if event.actual_value else 0,
                "threshold_min": float(event.threshold_min) if event.threshold_min else None,
                "threshold_max": float(event.threshold_max) if event.threshold_max else None,
                "status":        event.get_status_display(),
                "status_code":   event.status,
                "severity":      "resolved" if is_resolved else event.get_severity(),
                "is_resolved":   is_resolved,
                "timestamp":     event.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                "resolved_at":   event.resolved_at.strftime('%Y-%m-%d %H:%M:%S') if event.resolved_at else None,
                "duration_seconds": event.duration_seconds,
            })
        except Exception as e:
            logger.error(f"NotificationService serialize error: {e}")
            return

        with _lock:
            dead = []
            for client_id, q in _subscribers.items():
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead.append(client_id)
            for cid in dead:
                _subscribers.pop(cid, None)

        action = "RESOLVED" if is_resolved else "ALARM"
        logger.info(
            f"SSE [{action}] push → {len(_subscribers)} client(s): "
            f"sensor={event.sensor_id} {event.parameter} {event.status}"
        )

    @staticmethod
    def push_many(events: list) -> None:
        for event in events:
            NotificationService.push(event)

    @staticmethod
    def subscribe(client_id: str) -> queue.Queue:
        q = queue.Queue(maxsize=20)
        with _lock:
            _subscribers[client_id] = q
        logger.debug(f"SSE: client {client_id} subscribed ({len(_subscribers)} total)")
        return q

    @staticmethod
    def unsubscribe(client_id: str) -> None:
        with _lock:
            _subscribers.pop(client_id, None)
        logger.debug(f"SSE: client {client_id} unsubscribed")

    @staticmethod
    def active_count() -> int:
        return len(_subscribers)