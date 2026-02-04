# views/common.py (buat file baru)
from flask import Blueprint, jsonify, session
from database import get_session
from models.building import Building

common_bp = Blueprint('common', __name__)

@common_bp.route('/api/switch-building/<int:building_id>', methods=['POST'])
def switch_building(building_id):
    """Global endpoint untuk switch building"""
    db_session = get_session()
    try:
        building = db_session.query(Building).get(building_id)
        if not building:
            return jsonify({'error': 'Building not found'}), 404
        
        session['building_id'] = building_id
        
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


@common_bp.route('/api/current-building')
def get_current_building():
    """Get current active building"""
    building_id = session.get('building_id')
    if not building_id:
        return jsonify({'building': None})
    
    db_session = get_session()
    try:
        building = db_session.query(Building).get(building_id)
        if building:
            return jsonify({
                'building': {
                    'id': building.id,
                    'name': building.name,
                    'code': building.code
                }
            })
        return jsonify({'building': None})
    finally:
        db_session.close()