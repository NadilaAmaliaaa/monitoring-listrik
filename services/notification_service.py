# services/notification_service.py
"""
NotificationService — push alarm ke browser via SSE (Server-Sent Events).

SSE dipilih karena:
- Satu arah (server → client), cukup untuk notifikasi
- Tidak perlu library tambahan, Flask sudah support streaming
- Browser auto-reconnect jika koneksi putus
- Kompatibel dengan Flask threaded=True yang sudah dipakai di app.py
"""
import json
import queue
import threading
import logging

logger = logging.getLogger(__name__)

# { client_id: Queue } — satu entry per tab browser yang terhubung
_subscribers: dict = {}
_lock = threading.Lock()


class NotificationService:

    @staticmethod
    def push(event):
        """
        Kirim AlarmEvent ke semua subscriber SSE aktif.
        Skip jika status NORMAL (opsional — hapus kondisi ini
        jika ingin notifikasi 'alarm resolved' juga tampil di browser).
        """
        if event.status.upper() == "NORMAL":
            return

        try:
            payload = json.dumps({
                "type": "alarm",
                "id": event.id,
                "sensor_id": event.sensor_id,
                "parameter": event.parameter,
                "phase": event.sensor.phase if event.sensor else None,
                "actual_value": float(event.actual_value) if event.actual_value else 0,
                "threshold_min": float(event.threshold_min) if event.threshold_min else None,
                "threshold_max": float(event.threshold_max) if event.threshold_max else None,
                "status": event.get_status_display(),
                "severity": event.get_severity(),
                "timestamp": event.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            })
        except Exception as e:
            logger.error(f"NotificationService.push serialize error: {e}")
            return

        with _lock:
            dead = []
            for client_id, q in _subscribers.items():
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead.append(client_id)  # client lambat / disconnect

            for cid in dead:
                _subscribers.pop(cid, None)
                logger.debug(f"SSE: removed stale client {cid}")

        logger.info(f"SSE push → {len(_subscribers)} client(s): {event.parameter} {event.status}")

    @staticmethod
    def push_many(events: list):
        """Push beberapa AlarmEvent sekaligus."""
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
    def unsubscribe(client_id: str):
        with _lock:
            _subscribers.pop(client_id, None)
        logger.debug(f"SSE: client {client_id} unsubscribed ({len(_subscribers)} remaining)")

    @staticmethod
    def active_count() -> int:
        return len(_subscribers)