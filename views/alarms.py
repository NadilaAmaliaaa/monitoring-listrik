# views/alarms.py
from flask import Blueprint, render_template, jsonify, request, session
from controllers.alarms_controller import AlarmsController
from database import get_session
from models.building import Building

alarms_bp = Blueprint('alarms', __name__)


def get_current_building_id():
    """Get current active building from session"""
    return session.get('building_id')


def set_current_building(building_id):
    """Set active building in session"""
    session['building_id'] = building_id


@alarms_bp.route('/')
def index():
    """Render alarms history page"""
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
        
        # Get today's summary
        controller = AlarmsController(db_session, building_id=current_building_id)
        summary = controller.get_today_summary()
        
        return render_template(
            'alarms.html',
            buildings=buildings,
            current_building=current_building,
            summary=summary
        )
    finally:
        db_session.close()


@alarms_bp.route('/api/alarms')
def get_alarms():
    """Get alarm history with pagination and filters"""
    db_session = get_session()
    try:
        # Get query parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        parameter = request.args.get('parameter', None)
        phase = request.args.get('phase', None)
        status = request.args.get('status', None)
        search = request.args.get('search', None)
        
        # Get current building from session
        building_id = get_current_building_id()
        
        controller = AlarmsController(db_session, building_id=building_id)
        data = controller.get_alarms(
            page=page,
            per_page=per_page,
            parameter=parameter,
            phase=phase,
            status=status,
            search=search
        )
        
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db_session.close()


@alarms_bp.route('/api/summary')
def get_summary():
    """Get today's alarm summary"""
    db_session = get_session()
    try:
        building_id = get_current_building_id()
        
        controller = AlarmsController(db_session, building_id=building_id)
        summary = controller.get_today_summary()
        
        return jsonify(summary)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db_session.close()


@alarms_bp.route('/api/statistics')
def get_statistics():
    """Get alarm statistics for the last N days"""
    db_session = get_session()
    try:
        days = request.args.get('days', 7, type=int)
        building_id = get_current_building_id()
        
        controller = AlarmsController(db_session, building_id=building_id)
        stats = controller.get_statistics(days=days)
        
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db_session.close()


@alarms_bp.route('/api/parameter-distribution')
def get_parameter_distribution():
    """Get alarm distribution by parameter"""
    db_session = get_session()
    try:
        building_id = get_current_building_id()
        
        controller = AlarmsController(db_session, building_id=building_id)
        distribution = controller.get_parameter_distribution()
        
        return jsonify(distribution)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db_session.close()


@alarms_bp.route('/switch-building/<int:building_id>', methods=['POST'])
def switch_building(building_id):
    """Switch active building/department"""
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
                'code': building.code
            }
        })
    finally:
        db_session.close()