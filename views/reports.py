# views/reports.py
from flask import Blueprint, render_template, jsonify, request, send_file, session
from controllers.reports_controller import ReportsController
from database import get_session
from models.building import Building
import csv
import io

reports_bp = Blueprint('reports', __name__)

def get_current_building_id():
    """Get current active building from session"""
    return session.get('building_id')

def set_current_building(building_id):
    """Set active building in session"""
    session['building_id'] = building_id

@reports_bp.route('/')
def index():
    """Render reports page with building context"""
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
        
        return render_template(
            'reports.html',
            buildings=buildings,
            current_building=current_building
        )
    finally:
        db_session.close()


@reports_bp.route('/switch-building/<int:building_id>', methods=['POST'])
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


@reports_bp.route('/history')
def get_history():
    """Get history data for current building"""
    db_session = get_session()
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        period = request.args.get('period', 'hourly', type=str)

        if period not in ['hourly', 'daily', 'monthly']:
            return jsonify({'error': 'Invalid period'}), 400

        # Get current building from session
        building_id = get_current_building_id()
        
        controller = ReportsController(db_session, building_id=building_id)
        data = controller.get_history(page, per_page, period)

        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db_session.close()


@reports_bp.route('/generate-report', methods=['POST'])
def generate_report():
    """Generate report for current building"""
    db_session = get_session()

    try:
        payload = request.get_json()

        start_date = payload.get('start_date')
        end_date = payload.get('end_date')
        parameters = payload.get('parameters', 'all')
        format_type = payload.get('format', 'csv')

        # =============================
        # Validasi input
        # =============================
        if not start_date or not end_date:
            return jsonify({'error': 'start_date and end_date are required'}), 400

        if parameters not in ['all', 'power', 'energy']:
            return jsonify({'error': 'Invalid parameters'}), 400

        # =============================
        # Ambil building aktif
        # =============================
        building_id = get_current_building_id()
        if not building_id:
            return jsonify({'error': 'No building selected'}), 400

        controller = ReportsController(
            session=db_session,
            building_id=building_id
        )

        # =============================
        # Ambil data harian
        # =============================
        data = controller.get_data_for_report(
            start_date=start_date,
            end_date=end_date,
            parameters=parameters
        )

        if not data:
            return jsonify({'error': 'No data available'}), 404

        building = db_session.query(Building).get(building_id)

        # =============================
        # Generate file
        # =============================
        if format_type == 'csv':
            return controller.generate_csv_report(
                data=data,
                start_date=start_date,
                end_date=end_date,
                building_name=building.name,
                parameters=parameters
            )

        elif format_type == 'pdf':
            return controller.generate_pdf_report(
                data=data,
                start_date=start_date,
                end_date=end_date,
                building_name=building.name,
                parameters=parameters
            )

        return jsonify({'error': 'Invalid format'}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500

    finally:
        db_session.close()


# API endpoint to get all buildings
@reports_bp.route('/api/buildings')
def get_buildings():
    """Get list of all buildings"""
    db_session = get_session()
    try:
        buildings = db_session.query(Building).all()
        return jsonify({
            'buildings': [{
                'id': b.id,
                'name': b.name,
                'code': b.code
            } for b in buildings],
            'current_building_id': get_current_building_id()
        })
    finally:
        db_session.close()