from datetime import datetime, timedelta
from sqlalchemy import func, text, extract
from models.views import HourlyEnergyView, DailyEnergyView
from models.data import Sensor

class ReportsController:
    def __init__(self, session):
        self.session = session
    
    def get_history(self, page=1, per_page=10, period='hourly'):
        offset = (page - 1) * per_page
        now = datetime.utcnow()

        if period == 'hourly':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=1)

            query = (
                self.session.query(
                    HourlyEnergyView.date,
                    Sensor.phase,
                    HourlyEnergyView.avg_power,
                    HourlyEnergyView.peak_power,
                    HourlyEnergyView.total_kwh
                )
                .join(Sensor, Sensor.id == HourlyEnergyView.sensor_id)
                .filter(HourlyEnergyView.date >= start_date)
                .filter(HourlyEnergyView.date < end_date)
                .order_by(HourlyEnergyView.date.desc())
            )

        elif period == 'daily':
            start_date = now.replace(
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0
            )
            end_date = now

            query = (
                self.session.query(
                    DailyEnergyView.date,
                    Sensor.phase,
                    DailyEnergyView.avg_power,
                    DailyEnergyView.peak_power,
                    DailyEnergyView.total_energy_kwh
                )
                .join(Sensor, Sensor.id == DailyEnergyView.sensor_id)
                .filter(DailyEnergyView.date >= start_date)
                .filter(DailyEnergyView.date <= end_date)
                .order_by(DailyEnergyView.date.desc())
            )

        elif period == 'monthly':
            start_date = now.replace(
                month=1,
                day=1,
                hour=0,
                minute=0,
                second=0,
                microsecond=0
            )
            end_date = now

            query = (
                self.session.query(
                    func.date_trunc('month', DailyEnergyView.date).label('date'),
                    Sensor.phase,
                    func.avg(DailyEnergyView.avg_power).label('avg_power'),
                    func.max(DailyEnergyView.peak_power).label('peak_power'),
                    func.sum(DailyEnergyView.total_energy_kwh).label('total_kwh')
                )
                .join(Sensor, Sensor.id == DailyEnergyView.sensor_id)
                .filter(DailyEnergyView.date >= start_date)
                .filter(DailyEnergyView.date <= end_date)
                .group_by(
                    func.date_trunc('month', DailyEnergyView.date),
                    Sensor.phase
                )
                .order_by(text('date DESC'))
            )

        total = query.count()
        results = query.offset(offset).limit(per_page).all()

        # =====================
        # SERIALIZATION
        # =====================
        if period == 'hourly':
            data = [{
                'date': row.date.strftime('%H:%M'),
                'phase': row.phase,
                'avg_power': float(row.avg_power or 0),
                'peak_power': float(row.peak_power or 0),
                'total_kwh': float(row.total_kwh or 0)
            } for row in results]

        elif period == 'daily':
            data = [{
                'date': row.date.strftime('%Y-%m-%d'),
                'phase': row.phase,
                'avg_power': float(row.avg_power or 0),
                'peak_power': float(row.peak_power or 0),
                'total_kwh': float(row.total_energy_kwh or 0)
            } for row in results]

        else:  # monthly
            data = [{
                'date': row.date.strftime('%Y-%m'),
                'phase': row.phase,
                'avg_power': float(row.avg_power or 0),
                'peak_power': float(row.peak_power or 0),
                'total_kwh': float(row.total_kwh or 0)
            } for row in results]

        pages = max(1, (total + per_page - 1) // per_page)

        return {
            'data': data,
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': pages
        }

    
def get_data_for_report(self, start_date, end_date, parameters='all', period='daily'):
    # =====================
    # PARSE DATE
    # =====================
    if isinstance(start_date, str):
        start_date = datetime.fromisoformat(start_date).date()
    if isinstance(end_date, str):
        end_date = datetime.fromisoformat(end_date).date()

    # =====================
    # QUERY SOURCE
    # =====================
    if period == 'hourly':
        query = (
            self.session.query(
                HourlyEnergyView.date,
                Sensor.phase,
                HourlyEnergyView.avg_power,
                HourlyEnergyView.peak_power,
                HourlyEnergyView.total_kwh
            )
            .join(Sensor, Sensor.id == HourlyEnergyView.sensor_id)
            .filter(HourlyEnergyView.date.between(start_date, end_date))
            .order_by(HourlyEnergyView.date.asc())
        )

    else:  # daily (default)
        query = (
            self.session.query(
                DailyEnergyView.date,
                Sensor.phase,
                DailyEnergyView.avg_power,
                DailyEnergyView.peak_power,
                DailyEnergyView.total_energy_kwh
            )
            .join(Sensor, Sensor.id == DailyEnergyView.sensor_id)
            .filter(DailyEnergyView.date.between(start_date, end_date))
            .order_by(DailyEnergyView.date.asc())
        )

    results = query.all()

    # =====================
    # SERIALIZATION
    # =====================
    data = []

    for row in results:
        record = {
            'date': row.date.isoformat(),
            'phase': row.phase,
        }

        # Power
        if parameters in ['all', 'power']:
            record['avg_power'] = float(row.avg_power or 0)
            record['peak_power'] = float(row.peak_power or 0)

        # Energy
        if parameters in ['all', 'energy']:
            total_kwh = (
                row.total_kwh
                if period == 'hourly'
                else row.total_energy_kwh
            )
            record['total_kwh'] = float(total_kwh or 0)

        data.append(record)

    return data