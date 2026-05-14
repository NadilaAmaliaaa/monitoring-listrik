from flask import Flask, Response, session, redirect, url_for, request as flask_request, jsonify
from config import Config
from database import close_db
from models.building import Building
from models.data import Sensor, SensorReading
from models.alarm import AlarmEvent
from models.threshold2 import SensorThreshold
from models.user import User
import threading
import logging
import time
from datetime import timedelta

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ── Route publik — tidak perlu login ──────────────────────────────────────────
PUBLIC_ENDPOINTS = {
    'auth.login',
    'auth.logout',
    'static',
    'health_check',           # /health
    'debug_realtime_store',   # /api/debug/realtime-store
    # View mode — halaman publik tanpa login
    'viewmode.index',
    'viewmode.api_header',
    'viewmode.api_buildings',
    'viewmode.api_alarms',
    'viewmode.api_phase_balance',
    'viewmode.api_load',
}


def create_app():
    """Factory function untuk membuat Flask app"""

    app = Flask(__name__)
    app.config.from_object(Config)
    
    # ── Secret key & session lifetime ─────────────────────────────────────────
    if not app.config.get('SECRET_KEY'):
        app.secret_key = 'ganti-dengan-string-acak-panjang-di-env'
        logger.warning("⚠️  SECRET_KEY tidak ditemukan di Config. Pakai fallback — ganti sebelum production!")
    app.permanent_session_lifetime = timedelta(hours=8)

    logger.info("=" * 60)
    logger.info("INITIALIZING FLASK APPLICATION")
    logger.info("=" * 60)

    # ================================
    # Start MQTT Background Service
    # ================================
    logger.info("\n[1/4] Starting MQTT Background Service...")

    try:
        from mqtt.client import start_mqtt_hybrid

        def mqtt_worker():
            try:
                logger.info("MQTT worker thread started")
                client = start_mqtt_hybrid(loop_forever=False)
                if client:
                    logger.info("✓ MQTT Hybrid service started successfully")
                    logger.info("  → Realtime store: ENABLED (instant dashboard)")
                    logger.info("  → Database: ENABLED (historical data)")
                    while True:
                        time.sleep(1)
                else:
                    logger.error("✗ Failed to start MQTT service")
            except Exception as e:
                logger.error(f"✗ MQTT worker error: {e}")
                import traceback
                logger.error(traceback.format_exc())

        mqtt_thread = threading.Thread(target=mqtt_worker, daemon=True, name="MQTT-Hybrid-Worker")
        mqtt_thread.start()
        logger.info("✓ MQTT thread initialized")
        logger.info("Waiting for MQTT connection...")
        time.sleep(2)

    except ImportError as e:
        logger.error(f"✗ Failed to import MQTT module: {e}")
        logger.warning("⚠️  MQTT client not found. Trying fallback...")

        try:
            from mqtt.mqtt_client_integrated import start_mqtt_client

            def mqtt_worker_fallback():
                try:
                    manager = start_mqtt_client(loop_forever=False)
                    if manager:
                        logger.info("✓ Basic MQTT service started (DB only)")
                        while True:
                            time.sleep(1)
                    else:
                        logger.error("✗ Failed to start fallback MQTT service")
                except Exception as e:
                    logger.error(f"✗ Fallback MQTT error: {e}")

            mqtt_thread = threading.Thread(target=mqtt_worker_fallback, daemon=True, name="MQTT-Basic-Worker")
            mqtt_thread.start()
            logger.info("✓ Fallback MQTT thread initialized")
            time.sleep(2)

        except ImportError:
            logger.error("✗ No MQTT client available")

    except Exception as e:
        logger.error(f"✗ Unexpected error initializing MQTT: {e}")
        import traceback
        logger.error(traceback.format_exc())

    # ================================
    # Register Blueprints
    # ================================
    logger.info("\n[2/4] Registering Blueprints...")

    try:
        # Auth — harus didaftarkan pertama agar PUBLIC_ENDPOINTS dikenal before_request
        from views.auth import auth_bp
        app.register_blueprint(auth_bp, url_prefix='/auth')
        logger.info("✓ Auth blueprint registered")

        from views.dashboard import dashboard_bp
        app.register_blueprint(dashboard_bp)
        logger.info("✓ Dashboard blueprint registered")
        
        from views.analytics import analytics_bp
        app.register_blueprint(analytics_bp)
        logger.info("✓ Analytics blueprint registered")

        from views.reports import reports_bp
        app.register_blueprint(reports_bp, url_prefix='/reports')
        logger.info("✓ Reports blueprint registered")

        from views.common import common_bp
        app.register_blueprint(common_bp)
        logger.info("✓ Common blueprint registered")

        from views.alarms import alarms_bp
        app.register_blueprint(alarms_bp, url_prefix='/alarms')
        logger.info("✓ Alarms blueprint registered")

        from views.settings2 import settings_bp2
        app.register_blueprint(settings_bp2, url_prefix='/settings')
        logger.info("✓ Settings blueprint registered")

        from views.notifications import notifications_bp
        app.register_blueprint(notifications_bp, url_prefix='/notifications')
        logger.info("✓ Notifications blueprint registered")
        
        from views.viewmode import viewmode_bp
        app.register_blueprint(viewmode_bp)
        logger.info("✓ Viewmode blueprint registered")

    except Exception as e:
        logger.error(f"✗ Failed to register blueprints: {e}")
        import traceback
        logger.error(traceback.format_exc())

    # ================================
    # Global Login Guard
    # ================================
    logger.info("\n[3/4] Setting up auth & context processors...")

    @app.before_request
    def global_login_required():
        """
        Cek session login sebelum setiap request.
        Route dalam PUBLIC_ENDPOINTS dilewati tanpa pengecekan.
        SSE stream (/notifications/stream) juga dikecualikan agar
        tidak redirect di tengah koneksi EventSource.
        """
        endpoint = flask_request.endpoint

        # Lewati route publik dan SSE stream
        if endpoint in PUBLIC_ENDPOINTS:
            return
        if endpoint and endpoint.startswith('static'):
            return
        # SSE stream butuh koneksi panjang — jangan redirect
        if flask_request.path == '/notifications/stream':
            return
        
        # Cek flag invalidasi — session sudah di-logout tapi request masih jalan
        # (race condition: JS polling API saat logout diproses)
        # if session.get('_invalidated'):
        #     session.clear()
        #     if (flask_request.accept_mimetypes.accept_json and
        #             not flask_request.accept_mimetypes.accept_html):
        #         return jsonify({'error': 'Session invalidated'}), 401
        #     return redirect(url_for('auth.login'))
 
        # if 'user_id' not in session:
        #     logger.info(
        #         f"[AUTH BLOCK] user_id not in session — "
        #         f"endpoint={flask_request.endpoint} "
        #         f"path={flask_request.path} "
        #         f"session_keys={list(session.keys())}"
        #     )
        #     # API request → kembalikan 401 JSON bukan redirect HTML
        #     if (flask_request.accept_mimetypes.accept_json and
        #             not flask_request.accept_mimetypes.accept_html):
        #         return jsonify({'error': 'Unauthorized', 'login': url_for('auth.login')}), 401
 
        #     # Simpan URL tujuan, tapi HANYA untuk halaman non-root yang navigable
        #     _path = flask_request.path
        #     _last_segment = _path.split('/')[-1]
        #     _is_navigable = (
        #         flask_request.method == 'GET'
        #         and _path not in ('/', '', '/view')  # jangan simpan root/view
        #         and not _path.startswith('/static')
        #         and not _path.startswith('/api')
        #         and not _path.startswith('/favicon')
        #         and '.' not in _last_segment
        #     )
        #     if _is_navigable:
        #         session['next'] = flask_request.url
        #     else:
        #         session.pop('next', None)
 
        #     # Untuk root path '/', arahkan ke view mode dulu (bukan login)
        #     if flask_request.path in ('/', ''):
        #         return redirect(url_for('viewmode.index'))
 
        #     return redirect(url_for('auth.login'))
        
        # Handle root URL '/'
        if flask_request.path in ('/', ''):

            # Belum login → view mode
            if 'user_id' not in session:
                return redirect(url_for('viewmode.index'))

            # Sudah login → dashboard
            return redirect(url_for('dashboard.index'))
        # LAMA
        if flask_request.path.startswith('/api'):
            if 'user_id' not in session:
                return jsonify({'error': 'Unauthorized'}), 401

        if 'user_id' not in session:
            # API request → kembalikan 401 JSON bukan redirect HTML
            if (flask_request.accept_mimetypes.accept_json and
                    not flask_request.accept_mimetypes.accept_html):
                return jsonify({'error': 'Unauthorized', 'login': url_for('auth.login')}), 401

            # Simpan URL tujuan, tapi HANYA untuk halaman navigable
            # Mencegah session['next'] terisi '/favicon.ico' atau asset lainnya
            _path = flask_request.path
            _last_segment = _path.split('/')[-1]
            _is_navigable = (
                flask_request.method == 'GET'
                and not _path.startswith('/static')
                and not _path.startswith('/api')
                and not _path.startswith('/favicon')
                and '.' not in _last_segment  # skip ekstensi file (*.ico, *.png, dll)
            )
            if _is_navigable:
                session['next'] = flask_request.url

            return redirect(url_for('auth.login'))
    
    # @app.before_request
    # def no_cache(response):
    #      """
    #      Tambahkan header untuk mencegah caching di browser.
    #      Ini penting agar perubahan session (login/logout) langsung terasa tanpa harus refresh paksa.
    #      """
    #      if 'Cache-Control' not in response.headers:
    #          response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    #          response.headers['Pragma'] = 'no-cache'
    #          response.headers['Expires'] = '0'
    #      return response

    # ================================
    # Context Processors
    # ================================

    @app.context_processor
    def inject_context():
        """
        Inject building dan user context ke semua template.

        TIDAK query DB di sini — semua data diambil dari session yang
        sudah di-set saat login. Ini mencegah query DB ekstra di setiap
        request yang render template.

        Data yang di-set saat login (views/auth.py):
            session['building_id']      → int
            session['building_name']    → str
            session['building_code']    → str
            session['user_name']        → str
            session['username']         → str
        """
        if 'user_id' not in session:
            return {
                'buildings': [],
                'current_building': None,
                'current_user_name': '',
                'current_username': '',
            }

        # Buat object-like dict untuk current_building agar template
        # yang pakai current_building.name / current_building.code tetap bekerja
        building_id   = session.get('building_id')
        building_name = session.get('building_name', '')
        building_code = session.get('building_code', '')

        current_building = None
        if building_id:
            current_building = type('Building', (), {
                'id':   building_id,
                'name': building_name,
                'code': building_code,
            })()

        return {
            'buildings':         session.get('all_buildings', []),
            'current_building':  current_building,
            'current_user_name': session.get('user_name', ''),
            'current_username':  session.get('username', ''),
        }

    # ================================
    # Database Cleanup
    # ================================
    logger.info("\n[4/4] Setting up database cleanup...")

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        try:
            close_db()
            if exception:
                logger.warning(f"Request ended with exception: {exception}")
        except Exception as e:
            logger.error(f"Error during session cleanup: {e}")

    logger.info("✓ Database cleanup handler registered")

    # ================================
    # Health Check
    # ================================

    @app.route('/health')
    def health_check():
        from datetime import datetime
        try:
            from mqtt.realtime_store import get_all
            realtime_data = get_all()
            realtime_status = "active" if any(realtime_data.values()) else "empty"
        except Exception:
            realtime_status = "unavailable"

        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'service': 'Power Monitoring System',
            'realtime_store': realtime_status,
        })

    @app.route('/api/debug/realtime-store')
    def debug_realtime_store():
        try:
            from mqtt.realtime_store import get_all
            data = get_all()
            return jsonify({'status': 'success', 'realtime_store': data, 'has_data': any(data.values())})
        except Exception as e:
            return jsonify({'status': 'error', 'error': str(e)}), 500

    # ================================
    # Error Handlers
    # ================================

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Not found'}), 404

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal server error: {error}")
        return jsonify({'error': 'Internal server error'}), 500

    # ================================
    # Ready
    # ================================
    logger.info("\n" + "=" * 60)
    logger.info("✓ APPLICATION INITIALIZED SUCCESSFULLY")
    logger.info("=" * 60)
    logger.info("\nAvailable endpoints:")
    logger.info("  • Login:            http://localhost:5000/auth/login")
    logger.info("  • Dashboard:        http://localhost:5000/")
    logger.info("  • Health Check:     http://localhost:5000/health")
    logger.info("  • Debug Store:      http://localhost:5000/api/debug/realtime-store")
    logger.info("=" * 60 + "\n")

    return app


if __name__ == "__main__":
    app = create_app()

    HOST     = "0.0.0.0"
    PORT     = 5000
    DEBUG    = True
    THREADED = True

    logger.info(f"Starting Flask server on {HOST}:{PORT}")
    logger.info(f"Debug mode: {DEBUG}")
    logger.info(f"Threaded mode: {THREADED}")
    logger.info(f"\nAccess the application at:")
    logger.info(f"  • Local:   http://localhost:{PORT}")
    logger.info(f"  • Network: http://{HOST}:{PORT}")
    logger.info("\nPress Ctrl+C to stop the server\n")

    try:
        app.run(
            host=HOST,
            port=PORT,
            debug=DEBUG,
            threaded=THREADED,
            use_reloader=False,  # Disable reloader untuk menghindari double thread MQTT
        )
    except KeyboardInterrupt:
        logger.info("\n\nShutting down server...")
        logger.info("✓ Server stopped successfully")
    except Exception as e:
        logger.error(f"✗ Server error: {e}")