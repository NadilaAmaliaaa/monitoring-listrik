from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from database import Base


class Building(Base):
    __tablename__ = "buildings"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    code = Column(String(50), nullable=False, unique=True)
    
    # Relationships
    sensors = relationship("Sensor", back_populates="building", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Building(id={self.id}, name='{self.name}', code='{self.code}')>"
