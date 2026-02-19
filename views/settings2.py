# views/settings.py
from flask import Blueprint, render_template, jsonify, request, session
from controllers.threshold_controller2 import ThresholdController
from database import get_session
from models.building import Building

settings_bp2 = Blueprint('settings', __name__)


def get_current_building_id():
    return session.get('building_id')

def set_current_building(building_id):
    session['building_id'] = building_id


# ── Page ──────────────────────────────────────────────────────────────────────

@settings_bp2.route('/', strict_slashes=False)
def index():
    db_session = get_session()
    try:
        buildings = db_session.query(Building).all()
        current_building_id = get_current_building_id()

        if not current_building_id and buildings:
            current_building_id = buildings[0].id
            set_current_building(current_building_id)

        current_building = None
        if current_building_id:
            current_building = db_session.query(Building).get(current_building_id)

        controller = ThresholdController(db_session, building_id=current_building_id)
        thresholds = controller.get_all_settings()

        return render_template('auto_settings.html',
            buildings=buildings,
            current_building=current_building,
            thresholds=thresholds,
        )
    finally:
        db_session.close()


# ── API: GET ──────────────────────────────────────────────────────────────────

@settings_bp2.route('/api/settings/get', strict_slashes=False)
def get_settings():
    db_session = get_session()
    try:
        building_id = get_current_building_id()
        controller = ThresholdController(db_session, building_id=building_id)
        thresholds = controller.get_all_settings()

        data = []
        for t in thresholds:
            row = t.to_dict()
            row['phase'] = t.sensor.phase if t.sensor else None
            data.append(row)

        # Sertakan state auto global (True jika semua sensor auto)
        auto_state = controller.get_building_auto_state()
        return jsonify({'thresholds': data, 'auto_enabled': auto_state})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db_session.close()


# ── API: UPDATE manual ────────────────────────────────────────────────────────

@settings_bp2.route('/api/settings/sensor/<int:sensor_id>/update', methods=['PUT'], strict_slashes=False)
def update_settings(sensor_id):
    """Update manual — otomatis menonaktifkan auto mode untuk sensor ini."""
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


# ── API: RESET ────────────────────────────────────────────────────────────────

@settings_bp2.route('/api/settings/sensor/<int:sensor_id>/reset', methods=['POST'], strict_slashes=False)
def reset_settings(sensor_id):
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


# ── API: TOGGLE AUTO MODE (semua sensor di building) ─────────────────────────

@settings_bp2.route('/api/settings/auto-toggle', methods=['POST'], strict_slashes=False)
def toggle_auto_all():
    """
    Aktifkan atau nonaktifkan auto threshold untuk SEMUA sensor di building aktif.
    Dipanggil saat user klik toggle global di banner.

    Body: { "enabled": true, "days": 30 }
    """
    db_session = get_session()
    try:
        body = request.get_json(silent=True) or {}
        enabled = body.get('enabled', False)
        days    = body.get('days', 30)
        building_id = get_current_building_id()

        if not building_id:
            return jsonify({'success': False, 'error': 'Tidak ada building aktif.'}), 400

        controller = ThresholdController(db_session, building_id=building_id)
        results = controller.set_auto_mode_all(enabled=enabled, days=days)

        success_count = sum(1 for r in results if r['error'] is None)
        fail_count = len(results) - success_count

        return jsonify({
            'success': True,
            'enabled': enabled,
            'results': results,
            'summary': {
                'total': len(results),
                'success': success_count,
                'failed': fail_count,
            },
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db_session.close()


# ── API: TOGGLE AUTO MODE per sensor ─────────────────────────────────────────

@settings_bp2.route('/api/settings/sensor/<int:sensor_id>/auto-toggle', methods=['POST'], strict_slashes=False)
def toggle_auto_sensor(sensor_id):
    """
    Aktifkan/nonaktifkan auto threshold untuk 1 sensor.
    Body: { "enabled": true, "days": 30 }
    """
    db_session = get_session()
    try:
        body = request.get_json(silent=True) or {}
        enabled = body.get('enabled', False)
        days    = body.get('days', 30)
        building_id = get_current_building_id()

        controller = ThresholdController(db_session, building_id=building_id)
        threshold, preview, error = controller.set_auto_mode(sensor_id, enabled=enabled)

        if error:
            return jsonify({'success': False, 'error': error}), 422

        return jsonify({
            'success': True,
            'enabled': enabled,
            'data': threshold.to_dict(),
            'preview': preview,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db_session.close()


# ── API: PREVIEW auto (tanpa simpan) ─────────────────────────────────────────

@settings_bp2.route('/api/settings/sensor/<int:sensor_id>/auto-preview', strict_slashes=False)
def preview_auto_threshold(sensor_id):
    db_session = get_session()
    try:
        days = request.args.get('days', 30, type=int)
        building_id = get_current_building_id()

        controller = ThresholdController(db_session, building_id=building_id)
        calc, error = controller.calculate_auto_threshold(sensor_id, days=days)

        if error:
            return jsonify({'success': False, 'error': error}), 422

        return jsonify({'success': True, 'data': calc, 'days': days})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db_session.close()


# ── Switch Building ───────────────────────────────────────────────────────────

@settings_bp2.route('/switch-building/<int:building_id>', methods=['POST'], strict_slashes=False)
def switch_building(building_id):
    db_session = get_session()
    try:
        building = db_session.query(Building).get(building_id)
        if not building:
            return jsonify({'error': 'Building not found'}), 404
        set_current_building(building_id)
        return jsonify({'success': True, 'building': {
            'id': building.id, 'name': building.name, 'code': building.code,
        }})
    finally:
        db_session.close()