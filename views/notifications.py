# views/notifications.py
"""
SSE endpoint untuk notifikasi alarm real-time.

Daftarkan di app.py (setelah blueprint lain):
    from views.notifications import notifications_bp
    app.register_blueprint(notifications_bp, url_prefix='/notifications')
"""
import uuid
from flask import Blueprint, Response, stream_with_context, jsonify
from services.notification_service import NotificationService

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('/stream')
def stream():
    """
    Browser connect ke endpoint ini via EventSource.
    Setiap AlarmEvent baru dikirim sebagai SSE message.
    """
    client_id = str(uuid.uuid4())
    q = NotificationService.subscribe(client_id)

    def event_stream():
        # Konfirmasi koneksi berhasil
        yield 'data: {"type":"connected"}\n\n'
        try:
            while True:
                try:
                    # Tunggu event baru — timeout 25 detik lalu kirim heartbeat
                    payload = q.get(timeout=25)
                    yield f'data: {payload}\n\n'
                except Exception:
                    # Heartbeat — mencegah proxy/browser timeout
                    yield 'data: {"type":"heartbeat"}\n\n'
        except GeneratorExit:
            NotificationService.unsubscribe(client_id)

    return Response(
        stream_with_context(event_stream()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',   # penting untuk Nginx reverse proxy
            'Connection': 'keep-alive',
        }
    )


@notifications_bp.route('/status')
def status():
    """Debug: cek jumlah subscriber SSE aktif."""
    return jsonify({
        'active_subscribers': NotificationService.active_count()
    })