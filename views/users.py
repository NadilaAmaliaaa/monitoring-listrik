# views/users.py
from flask import Blueprint, render_template, jsonify, request, session, abort
from controllers.users_controller import UsersController
from views.auth import superadmin_required

users_bp = Blueprint('users', __name__)
ctrl = UsersController()


def _superadmin_check():
    """Raise 403 jika bukan superadmin."""
    if not session.get('is_super_admin'):
        abort(403)


@users_bp.route('/users')
@superadmin_required
def index():
    return render_template('users.html')


# ── API ───────────────────────────────────────────────────────────────────────

@users_bp.route('/api/users')
@superadmin_required
def api_list():
    return jsonify(ctrl.get_all_users())


@users_bp.route('/api/users/buildings')
@superadmin_required
def api_buildings():
    return jsonify(ctrl.get_buildings())


@users_bp.route('/api/users/<int:user_id>')
@superadmin_required
def api_get(user_id):
    user = ctrl.get_user(user_id)
    if not user:
        return jsonify({'error': 'Pengguna tidak ditemukan'}), 404
    return jsonify(user)


@users_bp.route('/api/users', methods=['POST'])
@superadmin_required
def api_create():
    data = request.get_json()
    required = ('name', 'username', 'password', 'building_id')
    if not all(data.get(k) for k in required):
        return jsonify({'error': 'Field name, username, password, dan building_id wajib diisi.'}), 400

    ok, err = ctrl.create_user(data)
    if not ok:
        return jsonify({'error': err}), 400
    return jsonify({'success': True}), 201


@users_bp.route('/api/users/<int:user_id>', methods=['PUT'])
@superadmin_required
def api_update(user_id):
    data = request.get_json()
    required = ('name', 'username', 'building_id')
    if not all(data.get(k) for k in required):
        return jsonify({'error': 'Field name, username, dan building_id wajib diisi.'}), 400

    ok, err = ctrl.update_user(user_id, data)
    if not ok:
        return jsonify({'error': err}), 400
    return jsonify({'success': True})


@users_bp.route('/api/users/<int:user_id>', methods=['DELETE'])
@superadmin_required
def api_delete(user_id):
    current_user_id = session.get('user_id')
    ok, err = ctrl.delete_user(user_id, current_user_id)
    if not ok:
        return jsonify({'error': err}), 400
    return jsonify({'success': True})