from flask import Blueprint, render_template, jsonify, session
from controllers.dashboard_controller import DashboardController
from database import get_session
from models.building import Building

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
def index():
    return render_template('dashboard.html')

@dashboard_bp.route('/api/dashboard/voltage')
def get_voltage():
    building_id = session.get('building_id')
    if not building_id:
        return jsonify({'error': 'No active building'}), 400

    db = get_session()
    try:
        building = db.query(Building).get(building_id)
        if not building:
            return jsonify({'error': 'Building not found'}), 404

        controller = DashboardController(
            session=None,
            building_id=building.id,
            building_code=building.code
        )

        return jsonify(controller.get_voltage())
    finally:
        db.close()

@dashboard_bp.route('/api/dashboard/current')
def get_current():
    building_id = session.get('building_id')
    if not building_id:
        return jsonify({'error': 'No active building'}), 400

    db = get_session()
    try:
        building = db.query(Building).get(building_id)
        if not building:
            return jsonify({'error': 'Building not found'}), 404

        controller = DashboardController(
            session=None,
            building_id=building.id,
            building_code=building.code
        )

        return jsonify(controller.get_current())
    finally:
        db.close()

@dashboard_bp.route('/api/dashboard/summary')
def get_summary():
    building_id = session.get('building_id')
    if not building_id:
        return jsonify({'error': 'No active building'}), 400

    db = get_session()
    try:
        controller = DashboardController(
            session=db,
            building_id=building_id
        )
        return jsonify(controller.get_summary())
    finally:
        db.close()

@dashboard_bp.route('/api/dashboard/power-factor')
def get_power_factor():
    building_id = session.get('building_id')
    if not building_id:
        return jsonify({'error': 'No active building'}), 400

    db = get_session()
    try:
        controller = DashboardController(
            session=db,
            building_id=building_id
        )
        return jsonify(controller.get_monthly_power_factor())
    finally:
        db.close()

@dashboard_bp.route('/api/dashboard/statistics')
def get_statistics():
    building_id = session.get('building_id')
    if not building_id:
        return jsonify({'error': 'No active building'}), 400

    db = get_session()
    try:
        controller = DashboardController(
            session=db,
            building_id=building_id
        )
        return jsonify(controller.get_24h_statistics())
    finally:
        db.close()