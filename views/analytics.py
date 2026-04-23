# views/analytics.py
from flask import Blueprint, render_template, jsonify, session, request
from controllers.analytics_controller import AnalyticsController

analytics_bp = Blueprint('analytics', __name__)


def _get_controller():
    building_id = session.get('building_id', 1)
    return AnalyticsController(building_id=building_id)


@analytics_bp.route('/analytics', strict_slashes=False)
def index():
    return render_template('analytics.html')


# ── API Endpoints ─────────────────────────────────────────────────────────────

@analytics_bp.route('/api/analytics/summary', strict_slashes=False)
def get_summary():
    days = int(request.args.get('days', 7))
    return jsonify(_get_controller().get_summary_cards())


@analytics_bp.route('/api/analytics/energy-trend', strict_slashes=False)
def get_energy_trend():
    period = request.args.get('period', 'daily')
    days   = int(request.args.get('days', 7))
    return jsonify(_get_controller().get_energy_trend(period=period, days=days))


@analytics_bp.route('/api/analytics/phase-balance', strict_slashes=False)
def get_phase_balance():
    days = int(request.args.get('days', 7))
    return jsonify(_get_controller().get_phase_balance(days=days))


@analytics_bp.route('/api/analytics/peak-load', strict_slashes=False)
def get_peak_load():
    days = int(request.args.get('days', 7))
    return jsonify(_get_controller().get_peak_load_trend(days=days))


@analytics_bp.route('/api/analytics/pf-history', strict_slashes=False)
def get_pf_history():
    days = int(request.args.get('days', 7))
    return jsonify(_get_controller().get_pf_history(days=days))