# controllers/users_controller.py
import logging
from database import get_session
from models.user import User
from models.building import Building

logger = logging.getLogger(__name__)


class UsersController:

    def get_all_users(self) -> list:
        db = get_session()
        try:
            rows = (
                db.query(User, Building.name.label('building_name'))
                .join(Building, User.building_id == Building.id)
                .order_by(User.building_id, User.name)
                .all()
            )
            return [
                {**u.to_dict(), 'building_name': bname}
                for u, bname in rows
            ]
        except Exception as e:
            logger.error(f"get_all_users: {e}", exc_info=True)
            return []
        finally:
            db.close()

    def get_user(self, user_id: int) -> dict | None:
        db = get_session()
        try:
            row = (
                db.query(User, Building.name.label('building_name'))
                .join(Building, User.building_id == Building.id)
                .filter(User.id == user_id)
                .first()
            )
            if not row:
                return None
            u, bname = row
            return {**u.to_dict(), 'building_name': bname}
        except Exception as e:
            logger.error(f"get_user: {e}", exc_info=True)
            return None
        finally:
            db.close()

    def get_buildings(self) -> list:
        db = get_session()
        try:
            return [
                {'id': b.id, 'name': b.name, 'code': b.code}
                for b in db.query(Building).order_by(Building.name).all()
            ]
        finally:
            db.close()

    def create_user(self, data: dict) -> tuple[bool, str]:
        """Return (success, error_message)."""
        db = get_session()
        try:
            # Validasi username unik
            existing = db.query(User).filter(User.username == data['username']).first()
            if existing:
                return False, f"Username '{data['username']}' sudah digunakan."

            user = User(
                building_id    = int(data['building_id']),
                name           = data['name'].strip(),
                username       = data['username'].strip(),
                password       = User.hash_password(data['password']),
                is_super_admin = bool(data.get('is_super_admin', False)),
            )
            db.add(user)
            db.commit()
            return True, ''
        except Exception as e:
            db.rollback()
            logger.error(f"create_user: {e}", exc_info=True)
            return False, str(e)
        finally:
            db.close()

    def update_user(self, user_id: int, data: dict) -> tuple[bool, str]:
        db = get_session()
        try:
            user = db.query(User).get(user_id)
            if not user:
                return False, 'Pengguna tidak ditemukan.'

            # Cek username konflik dengan user lain
            conflict = (
                db.query(User)
                .filter(User.username == data['username'], User.id != user_id)
                .first()
            )
            if conflict:
                return False, f"Username '{data['username']}' sudah digunakan."

            user.name           = data['name'].strip()
            user.username       = data['username'].strip()
            user.building_id    = int(data['building_id'])
            user.is_super_admin = bool(data.get('is_super_admin', False))

            # Update password hanya jika diisi
            if data.get('password'):
                user.password = User.hash_password(data['password'])

            db.commit()
            return True, ''
        except Exception as e:
            db.rollback()
            logger.error(f"update_user: {e}", exc_info=True)
            return False, str(e)
        finally:
            db.close()

    def delete_user(self, user_id: int, current_user_id: int) -> tuple[bool, str]:
        if user_id == current_user_id:
            return False, 'Tidak bisa menghapus akun sendiri.'
        db = get_session()
        try:
            user = db.query(User).get(user_id)
            if not user:
                return False, 'Pengguna tidak ditemukan.'
            db.delete(user)
            db.commit()
            return True, ''
        except Exception as e:
            db.rollback()
            logger.error(f"delete_user: {e}", exc_info=True)
            return False, str(e)
        finally:
            db.close()