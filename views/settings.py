# views/settings.py
from flask import Blueprint, render_template, jsonify, request, session
from controllers.threshold_controller import ThresholdController
from database import get_session
from models.building import Building

settings_bp = Blueprint('settings', __name__)


def get_current_building_id():
    """Get current active building from session"""
    return session.get('building_id')


def set_current_building(building_id):
    """Set active building in session"""
    session['building_id'] = building_id


# ── Page Route ────────────────────────────────────────────────────────────────

@settings_bp.route('/', strict_slashes=False)
def index():
    """
    Render settings page.
    Menampilkan threshold untuk setiap sensor di building aktif.
    """
    db_session = get_session()
    try:
        buildings = db_session.query(Building).all()
        current_building_id = get_current_building_id()

        # Set default building if none selected
        if not current_building_id and buildings:
            current_building_id = buildings[0].id
            set_current_building(current_building_id)

        current_building = None
        if current_building_id:
            current_building = db_session.query(Building).get(current_building_id)

        controller = ThresholdController(db_session, building_id=current_building_id)
        # List of SensorThreshold, satu per sensor di building aktif
        thresholds = controller.get_all_settings()

        return render_template(
            'settings.html',
            buildings=buildings,
            current_building=current_building,
            thresholds=thresholds,
        )
    finally:
        db_session.close()


# ── API: GET all sensors thresholds ──────────────────────────────────────────

@settings_bp.route('/api/settings/get')
def get_settings():
    """
    Return threshold settings for all sensors in the active building.
    """
    db_session = get_session()
    try:
        building_id = get_current_building_id()
        controller = ThresholdController(db_session, building_id=building_id)
        thresholds = controller.get_all_settings()

        data = []
        for t in thresholds:
            row = t.to_dict()
            # Sertakan phase dari relasi sensor untuk keperluan display
            row['phase'] = t.sensor.phase if t.sensor else None
            data.append(row)

        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db_session.close()


# ── API: UPDATE sensor threshold ──────────────────────────────────────────────

@settings_bp.route('/api/settings/sensor/<int:sensor_id>/update', methods=['PUT'])
def update_settings(sensor_id):
    """
    Update threshold settings for a specific sensor.

    Expected JSON body:
    {
        "voltage_min": 180,
        "voltage_max": 240,
        "voltage_min_enabled": true,
        "voltage_max_enabled": true,
        "current_min": 0.5,
        "current_max": 32.0,
        "current_min_enabled": false,
        "current_max_enabled": true
    }
    """
    db_session = get_session()
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'success': False, 'error': 'Request body tidak valid.'}), 400

        building_id = get_current_building_id()
        controller = ThresholdController(db_session, building_id=building_id)
        threshold, error = controller.update_settings(sensor_id, data)

        if error:
            return jsonify({'success': False, 'error': error}), 422

        return jsonify({'success': True, 'data': threshold.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db_session.close()


# ── API: RESET sensor threshold ───────────────────────────────────────────────

@settings_bp.route('/api/settings/sensor/<int:sensor_id>/reset', methods=['POST'])
def reset_settings(sensor_id):
    """Reset threshold settings for a specific sensor to factory defaults."""
    db_session = get_session()
    try:
        building_id = get_current_building_id()
        controller = ThresholdController(db_session, building_id=building_id)
        threshold, error = controller.reset_to_defaults(sensor_id)

        if error:
            return jsonify({'success': False, 'error': error}), 422

        return jsonify({'success': True, 'data': threshold.to_dict()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db_session.close()


# ── Switch Building ───────────────────────────────────────────────────────────

@settings_bp.route('/switch-building/<int:building_id>', methods=['POST'])
def switch_building(building_id):
    """Switch active building — threshold yang ditampilkan ikut berganti."""
    db_session = get_session()
    try:
        building = db_session.query(Building).get(building_id)
        if not building:
            return jsonify({'error': 'Building not found'}), 404

        set_current_building(building_id)

        return jsonify({
            'success': True,
            'building': {
                'id': building.id,
                'name': building.name,
                'code': building.code,
            }
        })
    finally:
        db_session.close()