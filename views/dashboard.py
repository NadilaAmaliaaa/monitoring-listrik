# views/dashboard.py
from flask import Blueprint, render_template, jsonify
from controllers.dashboard_controller import DashboardController
from database import get_session

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
def index():
    return render_template('dashboard.html')

@dashboard_bp.route('/api/dashboard/summary')
def get_summary():
    session = get_session()
    try:
        controller = DashboardController(session)
        data = controller.get_summary()
        
        if not data:
            return jsonify({'error': 'No data available'}), 404
        
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@dashboard_bp.route('/api/dashboard/voltage')
def get_voltage():
    try:
        controller = DashboardController(None)   # TIDAK pakai DB
        data = controller.get_voltage()

        if not data:
            return jsonify({'error': 'No data available'}), 404

        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/api/dashboard/current')
def get_current():
    session = get_session()
    try:
        controller = DashboardController(None)
        data = controller.get_current()
        
        if not data:
            return jsonify({'error': 'No data available'}), 404
        
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@dashboard_bp.route('/api/dashboard/power-factor')
def get_power_factor():
    session = get_session()
    try:
        controller = DashboardController(session)
        data = controller.get_monthly_power_factor()
        
        if not data:
            return jsonify({'error': 'No data available'}), 404
        
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@dashboard_bp.route('/api/dashboard/statistics')
def get_statistics():
    session = get_session()
    try:
        controller = DashboardController(session)
        data = controller.get_24h_statistics()
        
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()
        
@dashboard_bp.route('/api/dashboard/summary')
def get_summary():
    session = get_session()
    try:
        controller = DashboardController(session)
        data = controller.get_summary()
        
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()