from sqlalchemy import Column, Integer, Date, Float
from database import Base


class HourlyEnergyView(Base):
    __tablename__ = "view_hourly_energy"
    __table_args__ = {"info": {"is_view": True}}

    date = Column(Date, primary_key=True)
    sensor_id = Column(Integer, primary_key=True)

    power = Column(Float)
    avg_power = Column(Float)
    peak_power = Column(Float)
    total_kwh = Column(Float)
    total_cost = Column(Float)
    total_current = Column(Float)
    avg_current = Column(Float)
    avg_voltage = Column(Float)

    def __repr__(self):
        return f"<HourlyEnergyView(date={self.date}, sensor_id={self.sensor_id})>"


class DailyEnergyView(Base):
    __tablename__ = "view_daily_energy"
    __table_args__ = {"info": {"is_view": True}}

    date = Column(Date, primary_key=True)
    sensor_id = Column(Integer, primary_key=True)

    total_energy_kwh = Column(Float)
    avg_power = Column(Float)
    peak_power = Column(Float)
    avg_pf = Column(Float)
    total_current = Column(Float)
    avg_voltage = Column(Float)
    total_cost = Column(Float)

    def __repr__(self):
        return f"<DailyEnergyView(date={self.date}, sensor_id={self.sensor_id})>"