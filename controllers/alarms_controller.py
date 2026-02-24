# controllers/alarms_controller.py
from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_
from models.alarm import AlarmEvent
from models.data import Sensor
from models.building import Building


class AlarmsController:
    def __init__(self, session, building_id=None):
        self.session = session
        self.building_id = building_id

    def _get_base_query_filter(self, query, already_joined=False):
        if self.building_id:
            if not already_joined:
                query = query.join(Sensor, AlarmEvent.sensor_id == Sensor.id)
            query = query.filter(Sensor.building_id == self.building_id)
        return query

    def _determine_severity(self, status):
        status_lower = status.lower() if status else ''
        critical = {'over_voltage', 'under_voltage', 'over_current', 'over_limit'}
        warning  = {'under_current', 'low_pf', 'warning'}
        if status_lower in critical:
            return 'critical'
        if status_lower in warning:
            return 'warning'
        return 'normal'

    # ── Summary ───────────────────────────────────────────────────────────────

    def get_summary(self):
        now = datetime.utcnow()

        today_start     = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)
        week_start      = today_start - timedelta(days=today_start.weekday())
        last_week_start = week_start - timedelta(days=7)
        month_start     = today_start.replace(day=1)
        last_month_start = (
            month_start.replace(month=12, year=month_start.year - 1)
            if month_start.month == 1
            else month_start.replace(month=month_start.month - 1)
        )

        total_today      = self._count_alarms(today_start)
        total_yesterday  = self._count_alarms(yesterday_start, today_start)
        total_this_week  = self._count_alarms(week_start)
        total_last_week  = self._count_alarms(last_week_start, week_start)
        total_this_month = self._count_alarms(month_start)
        total_last_month = self._count_alarms(last_month_start, month_start)

        # Hitung alarm aktif saat ini (is_normal=False)
        active_count = (
            self.session.query(func.count(AlarmEvent.id))
            .join(Sensor, AlarmEvent.sensor_id == Sensor.id)
            .filter(AlarmEvent.is_normal == False)
            .filter(Sensor.building_id == self.building_id if self.building_id else True)
            .scalar() or 0
        )

        return {
            "daily": {
                "total": total_today,
                "previous": total_yesterday,
                "percentage_change": self._calculate_percentage(total_today, total_yesterday),
            },
            "weekly": {
                "total": total_this_week,
                "previous": total_last_week,
                "percentage_change": self._calculate_percentage(total_this_week, total_last_week),
            },
            "monthly": {
                "total": total_this_month,
                "previous": total_last_month,
                "percentage_change": self._calculate_percentage(total_this_month, total_last_month),
            },
            # Dipakai badge navbar dan frontend toast
            "active_count": active_count,
            "total_today": total_today,
        }

    # ── Get alarms (paginated) ────────────────────────────────────────────────

    def get_alarms(self, page=1, per_page=10, parameter=None, phase=None,
                   status=None, search=None):
        """
        Ambil riwayat alarm dengan pagination dan filter.

        Filter `status`:
            'all'      → semua alarm (default)
            'active'   → is_normal = False  (alarm masih berlangsung)
            'resolved' → is_normal = True   (sudah kembali normal)
        """
        offset = (page - 1) * per_page

        query = (
            self.session.query(AlarmEvent)
            .join(Sensor, AlarmEvent.sensor_id == Sensor.id)
        )

        # Filter building
        query = self._get_base_query_filter(query, already_joined=True)

        # Filter parameter
        if parameter and parameter != 'all':
            query = query.filter(AlarmEvent.parameter == parameter)

        # Filter fasa
        if phase and phase != 'all':
            query = query.filter(Sensor.phase == phase)

        # ── Filter kondisi (is_normal) — logika baru ──────────────────────────
        if status and status != 'all':
            if status == 'active':
                # Alarm masih berlangsung
                query = query.filter(AlarmEvent.is_normal == False)
            elif status == 'resolved':
                # Alarm sudah kembali normal
                query = query.filter(AlarmEvent.is_normal == True)

        # Search
        if search:
            query = query.filter(
                or_(
                    AlarmEvent.parameter.ilike(f'%{search}%'),
                    AlarmEvent.status.ilike(f'%{search}%'),
                )
            )

        query = query.order_by(AlarmEvent.timestamp.desc())

        total   = query.count()
        results = query.offset(offset).limit(per_page).all()

        data = []
        for alarm in results:
            try:
                alarm_dict = alarm.to_dict()
                unit = self._get_unit(alarm.parameter)
                alarm_dict['actual_value_display']  = f"{alarm.actual_value:.2f} {unit}"  if alarm.actual_value  is not None else "—"
                alarm_dict['threshold_min_display'] = f"{alarm.threshold_min:.2f} {unit}" if alarm.threshold_min is not None else "—"
                alarm_dict['threshold_max_display'] = f"{alarm.threshold_max:.2f} {unit}" if alarm.threshold_max is not None else "—"
                data.append(alarm_dict)
            except Exception as e:
                print(f"Error serializing alarm {alarm.id}: {e}")
                continue

        return {
            'data':     data,
            'total':    total,
            'page':     page,
            'per_page': per_page,
            'pages':    max(1, (total + per_page - 1) // per_page),
        }

    # ── Count helper ──────────────────────────────────────────────────────────

    def _count_alarms(self, start_date, end_date=None):
        """
        Hitung alarm dalam rentang waktu.
        Hanya hitung alarm nyata (is_normal abaikan — kita hitung event INSERT,
        bukan resolved). Satu alarm = satu INSERT row.
        """
        filters = [AlarmEvent.timestamp >= start_date]
        if end_date:
            filters.append(AlarmEvent.timestamp < end_date)

        query = (
            self.session.query(func.count(AlarmEvent.id))
            .filter(and_(*filters))
        )
        query = self._get_base_query_filter(query, already_joined=False)
        return query.scalar() or 0

    # ── Statistics ────────────────────────────────────────────────────────────

    def get_statistics(self, days=7):
        start_date = datetime.utcnow() - timedelta(days=days)

        query = self.session.query(
            func.date(AlarmEvent.timestamp).label('date'),
            AlarmEvent.status,
            func.count(AlarmEvent.id).label('count')
        ).filter(AlarmEvent.timestamp >= start_date)

        query = self._get_base_query_filter(query, already_joined=False)
        query = query.group_by(
            func.date(AlarmEvent.timestamp), AlarmEvent.status
        ).order_by(func.date(AlarmEvent.timestamp))

        stats = {}
        for row in query.all():
            date_str = row.date.isoformat()
            if date_str not in stats:
                stats[date_str] = {'critical': 0, 'warning': 0}
            severity = self._determine_severity(row.status)
            if severity in ('critical', 'warning'):
                stats[date_str][severity] += row.count

        return stats

    def get_parameter_distribution(self):
        query = (
            self.session.query(
                AlarmEvent.parameter,
                func.count(AlarmEvent.id).label('count')
            )
        )
        query = self._get_base_query_filter(query, already_joined=False)
        query = (
            query.group_by(AlarmEvent.parameter)
            .order_by(func.count(AlarmEvent.id).desc())
        )
        return [
            {'parameter': row.parameter, 'count': row.count}
            for row in query.all()
        ]
    
    @staticmethod
    def _calculate_percentage(current, previous):
        if previous > 0:
            return round(((current - previous) / previous) * 100, 1)
        return 100 if current > 0 else 0

    def _get_unit(self, parameter):
        """Get unit for parameter"""
        units = {
            'voltage': 'V',
            'current': 'A',
            'power': 'W',
            'power_factor': '',
            'frequency': 'Hz',
            'energy': 'kWh'
        }
        return units.get(parameter.lower(), '')
    
    def get_statistics(self, days=7):
        """Get alarm statistics for the last N days"""
        start_date = datetime.utcnow() - timedelta(days=days)
        
        query = self.session.query(
            func.date(AlarmEvent.timestamp).label('date'),
            AlarmEvent.status,
            func.count(AlarmEvent.id).label('count')
        ).filter(
            and_(
                AlarmEvent.timestamp >= start_date,
                AlarmEvent.status != 'normal'  # Exclude normal status
            )
        )
        
        # Apply building filter (will join Sensor if building_id is set)
        query = self._get_base_query_filter(query, already_joined=False)
        
        query = query.group_by(func.date(AlarmEvent.timestamp), AlarmEvent.status)
        query = query.order_by(func.date(AlarmEvent.timestamp))
        
        results = query.all()
        
        # Organize data by date and determine severity
        stats = {}
        for row in results:
            date_str = row.date.isoformat()
            if date_str not in stats:
                stats[date_str] = {'critical': 0, 'warning': 0, 'normal': 0}
            
            severity = self._determine_severity(row.status)
            stats[date_str][severity] += row.count
        
        return stats
    
    def get_parameter_distribution(self):
        """Get alarm distribution by parameter"""
        query = self.session.query(
            AlarmEvent.parameter,
            func.count(AlarmEvent.id).label('count')
        ).filter(AlarmEvent.status != 'normal')  # Exclude normal status
        
        # Apply building filter (will join Sensor if building_id is set)
        query = self._get_base_query_filter(query, already_joined=False)
        
        query = query.group_by(AlarmEvent.parameter)
        query = query.order_by(func.count(AlarmEvent.id).desc())
        
        results = query.all()
        
        return [
            {'parameter': row.parameter, 'count': row.count}
            for row in results
        ]