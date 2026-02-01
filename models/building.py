from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from database import Base


class Building(Base):
    __tablename__ = "buildings"

    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(100), nullable=False)

    sensors = relationship("Sensor", back_populates="building")

    def __repr__(self):
        return f"<Building {self.code} - {self.name}>"
