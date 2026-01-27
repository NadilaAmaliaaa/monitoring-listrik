from flask import Flask
from config import Config
from database import init_db, close_db
import threading


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # ================================
    # Start MQTT Background Service
    # ================================
    from mqtt.client import start_mqtt
    mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
    mqtt_thread.start()

    # ================================
    # Register Blueprints
    # ================================
    from views.dashboard import dashboard_bp
    # from views.alarms import alarms_bp
    # from views.reports import reports_bp      # butuh login
    # from views.thresholds import thresholds_bp # butuh login

    app.register_blueprint(dashboard_bp)
    # app.register_blueprint(alarms_bp)
    # app.register_blueprint(reports_bp, url_prefix="/admin")
    # app.register_blueprint(thresholds_bp, url_prefix="/admin")

    # ================================
    # Cleanup DB
    # ================================
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        close_db()


    return app


if __name__ == "__main__":
    app = create_app()
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
        threaded=True
    )
