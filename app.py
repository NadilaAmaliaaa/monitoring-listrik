from flask import Flask
from config import Config
from database import close_db
import threading
import logging
import time
from flask import session
from database import get_session
from models.building import Building
from models.data import Sensor, SensorReading, SensorThreshold
from models.alarm import AlarmEvent

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_app():
    """Factory function untuk membuat Flask app"""
    
    app = Flask(__name__)
    app.config.from_object(Config)
    
    logger.info("="*60)
    logger.info("INITIALIZING FLASK APPLICATION")
    logger.info("="*60)
    
    # ================================
    # Start MQTT Background Service
    # ================================
    logger.info("\n[1/3] Starting MQTT Background Service...")
    
    try:
        # ✅ FIXED: Import MQTT Hybrid (supports both DB + Realtime Store)
        from mqtt.client import start_mqtt_hybrid
        
        def mqtt_worker():
            """Worker function untuk MQTT client di thread terpisah"""
            try:
                logger.info("MQTT worker thread started")
                
                # Start MQTT Hybrid client in non-blocking mode
                client = start_mqtt_hybrid(loop_forever=False)
                
                if client:
                    logger.info("✓ MQTT Hybrid service started successfully")
                    logger.info("  → Realtime store: ENABLED (instant dashboard)")
                    logger.info("  → Database: ENABLED (historical data)")
                    
                    # Keep thread alive
                    while True:
                        time.sleep(1)
                else:
                    logger.error("✗ Failed to start MQTT service")
                    
            except Exception as e:
                logger.error(f"✗ MQTT worker error: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        # Start MQTT di background thread
        mqtt_thread = threading.Thread(
            target=mqtt_worker,
            daemon=True,
            name="MQTT-Hybrid-Worker"
        )
        mqtt_thread.start()
        logger.info("✓ MQTT thread initialized")
        
        # Give MQTT client time to connect
        logger.info("Waiting for MQTT connection...")
        time.sleep(2)
        
    except ImportError as e:
        logger.error(f"✗ Failed to import MQTT module: {e}")
        logger.warning("⚠️  MQTT client not found. System will run without MQTT.")
        logger.warning("    Required files:")
        logger.warning("    • mqtt/mqtt_hybrid.py")
        logger.warning("    • mqtt/realtime_store.py") 
        logger.warning("    • mqtt/mqtt_data_handler.py")
        
        # Try fallback to basic MQTT client (database only)
        try:
            logger.info("Attempting fallback to basic MQTT client...")
            from mqtt.mqtt_client_integrated import start_mqtt_client
            
            def mqtt_worker_fallback():
                try:
                    logger.info("MQTT fallback worker started")
                    manager = start_mqtt_client(loop_forever=False)
                    
                    if manager:
                        logger.info("✓ Basic MQTT service started (DB only)")
                        logger.warning("  → Realtime store: DISABLED")
                        logger.info("  → Database: ENABLED")
                        
                        while True:
                            time.sleep(1)
                    else:
                        logger.error("✗ Failed to start fallback MQTT service")
                except Exception as e:
                    logger.error(f"✗ Fallback MQTT error: {e}")
            
            mqtt_thread = threading.Thread(
                target=mqtt_worker_fallback,
                daemon=True,
                name="MQTT-Basic-Worker"
            )
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
    logger.info("\n[2/3] Registering Blueprints...")
    
    try:
        from views.dashboard import dashboard_bp
        app.register_blueprint(dashboard_bp)
        logger.info("✓ Dashboard blueprint registered")
        
        from views.reports import reports_bp
        app.register_blueprint(reports_bp, url_prefix='/reports')
        logger.info("✓ Reports blueprint registered")
        
        from views.common import common_bp
        app.register_blueprint(common_bp)
        
        from views.alarms import alarms_bp
        app.register_blueprint(alarms_bp, url_prefix='/alarms')
        
    except Exception as e:
        logger.error(f"✗ Failed to register blueprints: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
    @app.context_processor
    def inject_building_context():
        """Inject building data ke semua template"""
        db_session = get_session()
        try:
            buildings = db_session.query(Building).all()
            current_building_id = session.get('building_id')
            
            # Set default jika belum ada
            if not current_building_id and buildings:
                current_building_id = buildings[0].id
                session['building_id'] = current_building_id
            
            current_building = None
            if current_building_id:
                current_building = db_session.get(Building, current_building_id)
            
            return {
                'buildings': buildings,
                'current_building': current_building
            }
        except:
            return {
                'buildings': [],
                'current_building': None
            }
        finally:
            db_session.close()

    # ================================
    # Database Cleanup Handler
    # ================================
    logger.info("\n[3/3] Setting up database cleanup...")
    
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        """Cleanup database session setelah request"""
        try:
            close_db()
            if exception:
                logger.warning(f"Request ended with exception: {exception}")
        except Exception as e:
            logger.error(f"Error during session cleanup: {e}")
    
    logger.info("✓ Database cleanup handler registered")

    # ================================
    # Health Check Endpoint
    # ================================
    @app.route('/health')
    def health_check():
        """Endpoint untuk health check"""
        from flask import jsonify
        from datetime import datetime
        
        # Check realtime store status
        try:
            from mqtt.realtime_store import get_all
            realtime_data = get_all()
            realtime_status = "active" if any(realtime_data.values()) else "empty"
        except:
            realtime_status = "unavailable"
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'service': 'Power Monitoring System',
            'realtime_store': realtime_status
        })
    
    logger.info("✓ Health check endpoint registered")
    
    # ================================
    # Realtime Store Check Endpoint (Debug)
    # ================================
    @app.route('/api/debug/realtime-store')
    def debug_realtime_store():
        """Debug endpoint untuk cek realtime store"""
        from flask import jsonify
        
        try:
            from mqtt.realtime_store import get_all
            data = get_all()
            
            return jsonify({
                'status': 'success',
                'realtime_store': data,
                'has_data': any(data.values())
            })
        except Exception as e:
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500
    
    logger.info("✓ Debug endpoint registered: /api/debug/realtime-store")
    
    # ================================
    # Error Handlers
    # ================================
    @app.errorhandler(404)
    def not_found(error):
        from flask import jsonify
        return jsonify({'error': 'Not found'}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        from flask import jsonify
        logger.error(f"Internal server error: {error}")
        return jsonify({'error': 'Internal server error'}), 500
    
    # ================================
    # Application Ready
    # ================================
    logger.info("\n" + "="*60)
    logger.info("✓ APPLICATION INITIALIZED SUCCESSFULLY")
    logger.info("="*60)
    logger.info("\nAvailable endpoints:")
    logger.info("  • Dashboard:        http://localhost:5000/")
    logger.info("  • Health Check:     http://localhost:5000/health")
    logger.info("  • Debug Store:      http://localhost:5000/api/debug/realtime-store")
    logger.info("  • Voltage API:      http://localhost:5000/api/dashboard/voltage")
    logger.info("  • Current API:      http://localhost:5000/api/dashboard/current")
    logger.info("="*60 + "\n")
    
    return app


if __name__ == "__main__":
    """Run the Flask application"""
    
    app = create_app()
    
    # Configuration
    HOST = "0.0.0.0"
    PORT = 5000
    DEBUG = True
    THREADED = True
    
    logger.info(f"Starting Flask server on {HOST}:{PORT}")
    logger.info(f"Debug mode: {DEBUG}")
    logger.info(f"Threaded mode: {THREADED}")
    logger.info("\nAccess the application at:")
    logger.info(f"  • Local:   http://localhost:{PORT}")
    logger.info(f"  • Network: http://{HOST}:{PORT}")
    logger.info("\nPress Ctrl+C to stop the server\n")
    
    try:
        app.run(
            host=HOST,
            port=PORT,
            debug=DEBUG,
            threaded=THREADED,
            use_reloader=False  # Disable reloader untuk menghindari double thread MQTT
        )
    except KeyboardInterrupt:
        logger.info("\n\nShutting down server...")
        logger.info("✓ Server stopped successfully")
    except Exception as e:
        logger.error(f"✗ Server error: {e}")