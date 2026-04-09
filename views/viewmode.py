# views/viewmode.py
from flask import Blueprint, render_template, jsonify
from controllers.viewmode_controller import ViewModeController

viewmode_bp = Blueprint('viewmode', __name__)
ctrl = ViewModeController()


@viewmode_bp.route('/view')
def index():
    """Halaman publik — tidak butuh login."""
    return render_template('viewmode.html')


@viewmode_bp.route('/api/view/header')
def api_header():
    return jsonify(ctrl.get_header_stats())


@viewmode_bp.route('/api/view/buildings')
def api_buildings():
    return jsonify(ctrl.get_building_cards())


@viewmode_bp.route('/api/view/alarms')
def api_alarms():
    return jsonify(ctrl.get_active_alarms())


@viewmode_bp.route('/api/view/phase-balance')
def api_phase_balance():
    return jsonify(ctrl.get_phase_balance())


@viewmode_bp.route('/api/view/load-distribution')
def api_load():
    return jsonify(ctrl.get_load_distribution())