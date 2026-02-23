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
            # Only join Sensor if not already joined
            if not already_joined:
                query = query.join(Sensor, AlarmEvent.sensor_id == Sensor.id)
            # Apply building filter
            query = query.filter(Sensor.building_id == self.building_id)
        return query
    
    def _determine_severity(self, status):
        """Determine severity based on status"""
        status_lower = status.lower() if status else ''
        
        critical_statuses = ['over_voltage', 'under_voltage', 'over_current', 'over_limit']
        warning_statuses = ['under_current', 'low_pf', 'warning']
        
        if status_lower in critical_statuses:
            return 'critical'
        elif status_lower in warning_statuses:
            return 'warning'
        else:
            return 'normal'
    
    def get_summary(self):
        """Get alarm summary: daily, weekly, monthly"""
        now = datetime.utcnow()

        # ─────────────────────────────────────
        # DAILY
        # ─────────────────────────────────────
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)

        total_today = self._count_alarms(today_start, None)
        total_yesterday = self._count_alarms(yesterday_start, today_start)

        daily_percentage = self._calculate_percentage(total_today, total_yesterday)

        # ─────────────────────────────────────
        # WEEKLY
        # ─────────────────────────────────────
        week_start = today_start - timedelta(days=today_start.weekday())
        last_week_start = week_start - timedelta(days=7)

        total_this_week = self._count_alarms(week_start, None)
        total_last_week = self._count_alarms(last_week_start, week_start)

        weekly_percentage = self._calculate_percentage(total_this_week, total_last_week)

        # ─────────────────────────────────────
        # MONTHLY
        # ─────────────────────────────────────
        month_start = today_start.replace(day=1)
        if month_start.month == 1:
            last_month_start = month_start.replace(year=month_start.year - 1, month=12)
        else:
            last_month_start = month_start.replace(month=month_start.month - 1)

        total_this_month = self._count_alarms(month_start, None)
        total_last_month = self._count_alarms(last_month_start, month_start)

        monthly_percentage = self._calculate_percentage(total_this_month, total_last_month)

        return {
            "daily": {
                "total": total_today,
                "previous": total_yesterday,
                "percentage_change": daily_percentage,
            },
            "weekly": {
                "total": total_this_week,
                "previous": total_last_week,
                "percentage_change": weekly_percentage,
            },
            "monthly": {
                "total": total_this_month,
                "previous": total_last_month,
                "percentage_change": monthly_percentage,
            },
        }
    
    def get_alarms(self, page=1, per_page=10, parameter=None, phase=None, status=None, search=None):
        """Get paginated alarm history with filters"""
        offset = (page - 1) * per_page
        
        # Base query - join with Sensor to get phase info
        query = self.session.query(AlarmEvent).join(Sensor, AlarmEvent.sensor_id == Sensor.id)
        
        # Apply building filter (Sensor already joined, so pass already_joined=True)
        query = self._get_base_query_filter(query, already_joined=True)
        
        # Apply filters
        if parameter and parameter != 'all':
            query = query.filter(AlarmEvent.parameter == parameter)
        
        if phase and phase != 'all':
            query = query.filter(Sensor.phase == phase)
        
        if status and status != 'all':
            # Filter based on severity derived from status
            if status == 'critical':
                critical_statuses = ['over_voltage', 'under_voltage', 'over_current', 'over_limit']
                query = query.filter(AlarmEvent.status.in_(critical_statuses))
            elif status == 'warning':
                warning_statuses = ['under_current', 'low_pf', 'warning']
                query = query.filter(AlarmEvent.status.in_(warning_statuses))
            elif status == 'normal':
                query = query.filter(AlarmEvent.status == 'normal')
        
        if search:
            query = query.filter(
                or_(
                    AlarmEvent.parameter.ilike(f'%{search}%'),
                    AlarmEvent.status.ilike(f'%{search}%')
                )
            )
        
        # Order by timestamp descending
        query = query.order_by(AlarmEvent.timestamp.desc())
        
        # Get total count
        total = query.count()
        
        # Get paginated results
        results = query.offset(offset).limit(per_page).all()
        
        # Serialize data
        data = []
        for alarm in results:
            try:
                alarm_dict = alarm.to_dict()
                
                # Add unit based on parameter
                unit = self._get_unit(alarm.parameter)
                alarm_dict['actual_value_display'] = f"{alarm.actual_value:.1f} {unit}" if alarm.actual_value else "-"
                alarm_dict['threshold_min_display'] = f"{alarm.threshold_min:.1f} {unit}" if alarm.threshold_min else "-"
                alarm_dict['threshold_max_display'] = f"{alarm.threshold_max:.1f} {unit}" if alarm.threshold_max else "-"
                
                data.append(alarm_dict)
            except Exception as e:
                # Skip problematic records and log
                print(f"Error serializing alarm {alarm.id}: {str(e)}")
                continue
        
        pages = max(1, (total + per_page - 1) // per_page)
        
        return {
            'data': data,
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': pages
        }
    
    def _count_alarms(self, start_date, end_date=None):
        query = self.session.query(func.count(AlarmEvent.id))

        filters = [
            AlarmEvent.timestamp >= start_date,
            AlarmEvent.status != 'normal'
        ]

        if end_date:
            filters.append(AlarmEvent.timestamp < end_date)

        query = query.filter(and_(*filters))
        query = self._get_base_query_filter(query, already_joined=False)

        return query.scalar() or 0
    
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