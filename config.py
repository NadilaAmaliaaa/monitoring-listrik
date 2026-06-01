"""
Configuration file - Load dari environment variables
"""

import os
from dotenv import load_dotenv

# Load environment variables dari .env file
load_dotenv()


class Config:
    """Flask Configuration"""
    
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    
    # Database Configuration
    DB_NAME = os.getenv('DB_NAME', 'energy_monitoring')
    DB_USER = os.getenv('DB_USER', 'postgres')
    DB_PASSWORD = os.getenv('DB_PASSWORD', 'nadila')
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = os.getenv('DB_PORT', '5432')
    
    # Database Pool
    DB_POOL_MINCONN = int(os.getenv('DB_POOL_MINCONN', '1'))
    DB_POOL_MAXCONN = int(os.getenv('DB_POOL_MAXCONN', '10'))
    
    # SQLAlchemy Database URI
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': DB_POOL_MAXCONN,
        'pool_pre_ping': True,
        'pool_recycle': 3600,
        'max_overflow': 10
    }
    
    # MQTT Configuration
    MQTT_BROKER = os.getenv('MQTT_BROKER', '10.1.1.55')
    MQTT_PORT = int(os.getenv('MQTT_PORT', '1883'))
    MQTT_KEEPALIVE = 60
    MQTT_RECONNECT_DELAY_SEC = 5
    
    # MQTT Topics
    MQTT_TOPIC_PATTERN = os.getenv('MQTT_TOPIC_PATTERN', 'sensor/#')
    MQTT_TOPIC_PREDICT = os.getenv('MQTT_TOPIC_PREDICT', 'predict/pub')
    MQTT_TOPIC_PREDICT_RESULT = os.getenv('MQTT_TOPIC_PREDICT_RESULT', 'predict/result')
    
    # Energy Calculation
    TARIF_PER_KWH = float(os.getenv('TARIF_PER_KWH', '1533.0'))
    PPJ = float(os.getenv('PPJ', '0.05'))  # 5%
    
    # Aggregation Configuration
    MAX_BUCKETS_PER_SENSOR = int(os.getenv('MAX_BUCKETS_PER_SENSOR', '100'))
    FLUSH_INTERVAL_SEC = int(os.getenv('FLUSH_INTERVAL_SEC', '15'))
    CLEANUP_INTERVAL_MIN = int(os.getenv('CLEANUP_INTERVAL_MIN', '5'))
    BUCKET_CUTOFF_SEC = int(os.getenv('BUCKET_CUTOFF_SEC', '10'))
    OLD_BUCKET_THRESHOLD_HOURS = int(os.getenv('OLD_BUCKET_THRESHOLD_HOURS', '1'))


# Database config dictionary untuk backward compatibility
DB_CONFIG = {
    'dbname': Config.DB_NAME,
    'user': Config.DB_USER,
    'password': Config.DB_PASSWORD,
    'host': Config.DB_HOST,
    'port': Config.DB_PORT
}


# MQTT config untuk mudah diakses
MQTT_CONFIG = {
    'broker': Config.MQTT_BROKER,
    'port': Config.MQTT_PORT,
    'keepalive': Config.MQTT_KEEPALIVE,
    'topics': {
        'pattern': Config.MQTT_TOPIC_PATTERN,
        'predict': Config.MQTT_TOPIC_PREDICT,
        'predict_result': Config.MQTT_TOPIC_PREDICT_RESULT
    }
}