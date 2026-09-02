# models/user.py
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = {'extend_existing': True}

    id          = Column(Integer, primary_key=True, autoincrement=True)
    building_id = Column(Integer, ForeignKey("buildings.id"), nullable=False)
    name        = Column(String(100), nullable=False)
    username    = Column(String(30), nullable=False, unique=True)
    password    = Column(String(255), nullable=False)
    
    is_super_admin = Column(Boolean, nullable=False, default=False)

    # building = relationship("Building", back_populates="users")

    def check_password(self, password: str) -> bool:
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password, password)

    @staticmethod
    def hash_password(plain: str) -> str:
        """Gunakan saat membuat/update user. Contoh: user.password = User.hash_password('abc123')"""
        from werkzeug.security import generate_password_hash
        return generate_password_hash(plain)

    def to_dict(self):
        return {
            "id":          self.id,
            "building_id": self.building_id,
            "name":        self.name,
            "username":    self.username,
            "is_super_admin": self.is_super_admin,
        }

    def __repr__(self):
        return f"<User {self.username} building={self.building_id}>"