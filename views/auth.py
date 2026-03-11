# views/auth.py
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from database import get_session

# Import semua model agar SQLAlchemy registry lengkap sebelum query User
from models.building import Building          # noqa
from models.data import Sensor, SensorReading # noqa
from models.alarm import AlarmEvent           # noqa
from models.threshold2 import SensorThreshold # noqa
from models.user import User

auth_bp = Blueprint('auth', __name__)


# ── Decorator ─────────────────────────────────────────────────────────────────

def login_required(f):
    """
    Decorator untuk semua route yang butuh login.
    Jika belum login → redirect ke halaman login.
    Jika request adalah API (Accept: application/json) → return 401 JSON.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            if request.accept_mimetypes.accept_json and \
               not request.accept_mimetypes.accept_html:
                return jsonify({'error': 'Unauthorized', 'redirect': url_for('auth.login')}), 401
            # Simpan URL tujuan agar bisa redirect balik setelah login
            session['next'] = request.url
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    """Ambil user yang sedang login dari session. None jika belum login."""
    user_id = session.get('user_id')
    if not user_id:
        return None
    db = get_session()
    try:
        return db.query(User).get(user_id)
    finally:
        db.close()


# ── Routes ────────────────────────────────────────────────────────────────────

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # Sudah login → langsung ke dashboard
    if 'user_id' in session:
        return redirect(url_for('dashboard.index'))

    error = None

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            error = 'Username dan password wajib diisi.'
        else:
            db = get_session()
            try:
                user = db.query(User).filter(User.username == username).first()

                if user and user.check_password(password):
                    # Hapus session lama untuk mencegah race condition
                    session.clear()
                    # Ambil data building user untuk disimpan ke session
                    # agar context_processor tidak perlu query DB setiap request
                    building = db.query(Building).get(user.building_id)

                    session.permanent = True
                    session['user_id']       = user.id
                    session['user_name']     = user.name
                    session['username']      = user.username
                    session['building_id']   = user.building_id
                    session['building_name'] = building.name if building else ''
                    session['building_code'] = building.code if building else ''

                    # Simpan daftar semua building untuk dropdown navbar
                    # (hanya id, name, code — tidak ada object SQLAlchemy)
                    all_buildings = db.query(Building).all()
                    session['all_buildings'] = [
                        {'id': b.id, 'name': b.name, 'code': b.code}
                        for b in all_buildings
                    ]

                    # Redirect ke halaman yang dituju sebelum login, atau dashboard
                    next_url = session.pop('next', None)
                    return redirect(next_url or url_for('dashboard.index'))
                else:
                    error = 'Username atau password salah.'
            finally:
                db.close()

    return render_template('login.html', error=error)

@auth_bp.route('/logout')
def logout():
    session.clear()

    resp = redirect(url_for('auth.login'))
    resp.delete_cookie('session')

    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'

    return resp


# @auth_bp.route('/logout')
# def logout():
#     # Hapus semua key session secara eksplisit + clear()
#     # Mencegah context_processor re-inject building_id setelah logout
#     for key in ('user_id', 'user_name', 'username', 'building_id', 'next'):
#         session.pop(key, None)
#     session.clear()
#     # modified=True memastikan Flask benar-benar kirim Set-Cookie untuk invalidasi
#     session.modified = True
#     return redirect(url_for('auth.login'))