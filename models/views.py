from sqlalchemy import Column, Integer, Date, Float
from database import db


class HourlyEnergyView(db.Model):
    __tablename__ = "view_hourly_energy"
    __table_args__ = {"info": {"is_view": True}}

    date = Column(Date, primary_key=True)
    sensor_id = Column(Integer, primary_key=True)

    power = Column(Float)
    avg_power = Column(Float)
    peak_power = Column(Float)
    total_kwh = Column(Float)
    total_cost = Column(Float)


class DailyEnergyView(db.Model):
    __tablename__ = "view_daily_energy"
    __table_args__ = {"info": {"is_view": True}}

    date = Column(Date, primary_key=True)
    sensor_id = Column(Integer, primary_key=True)

    total_energy_kwh = Column(Float)
    avg_power = Column(Float)
    peak_power = Column(Float)
    total_cost = Column(Float)
