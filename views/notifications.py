# views/notifications.py
"""
SSE endpoint untuk notifikasi alarm real-time.
"""
import uuid
import logging
from flask import Blueprint, Response, stream_with_context, jsonify
from services.notification_service import NotificationService

notifications_bp = Blueprint('notifications', __name__)
logger = logging.getLogger(__name__)


@notifications_bp.route('/stream')
def stream():
    """
    Browser connect ke endpoint ini via EventSource.
    Setiap AlarmEvent baru dikirim sebagai SSE message.

    Penanganan disconnect:
    - GeneratorExit  : browser tutup tab / navigasi (clean disconnect)
    - BrokenPipeError: koneksi putus mendadak
    - finally block  : SELALU unsubscribe agar queue tidak leak
    """
    client_id = str(uuid.uuid4())
    q = NotificationService.subscribe(client_id)
    logger.debug(f"SSE client connected: {client_id}")

    def event_stream():
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    payload = q.get(timeout=25)
                    yield f'data: {payload}\n\n'
                except Exception:
                    # Queue timeout → heartbeat
                    yield 'data: {"type":"heartbeat"}\n\n'
        except GeneratorExit:
            logger.debug(f"SSE client disconnected (GeneratorExit): {client_id}")
        except BrokenPipeError:
            logger.debug(f"SSE client disconnected (BrokenPipe): {client_id}")
        except Exception as e:
            logger.warning(f"SSE stream error for {client_id}: {e}")
        finally:
            # Selalu unsubscribe — mencegah queue + thread leak
            NotificationService.unsubscribe(client_id)
            logger.debug(f"SSE client unsubscribed: {client_id}")

    return Response(
        stream_with_context(event_stream()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control':     'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection':        'keep-alive',
        }
    )


@notifications_bp.route('/status')
def status():
    """Debug: cek jumlah subscriber SSE aktif."""
    return jsonify({'active_subscribers': NotificationService.active_count()})