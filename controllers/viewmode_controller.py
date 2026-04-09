# controllers/viewmode_controller.py
"""
ViewModeController — data untuk halaman publik (tanpa login).

Sumber data:
  - realtime_store : data MQTT real-time per sensor (tegangan, arus, daya)
  - DailyEnergyView: energi & biaya hari ini dan bulan ini per sensor
  - AlarmEvent     : alarm aktif saat ini
"""
import logging
from datetime import date, datetime
from collections import defaultdict
from sqlalchemy import func, and_

from database import get_session
from models.data import Sensor, SensorReading
from models.building import Building
from models.alarm import AlarmEvent
from models.views import HourlyEnergyView, DailyEnergyView

logger = logging.getLogger(__name__)


def _realtime_all():
    """Ambil semua data realtime dari store. Return dict kosong jika tidak tersedia."""
    try:
        from mqtt.realtime_store import get_all
        return get_all() or {}
    except Exception:
        return {}


class ViewModeController:

    # ── Header: total energi & biaya bulan ini ────────────────────────────────

    def get_header_stats(self) -> dict:
        """
        Total energi (kWh) dan estimasi biaya (Rp) seluruh building bulan ini.
        """
        db = get_session()
        try:
            month_start = date.today().replace(day=1)
            rows = (
                db.query(
                    func.sum(DailyEnergyView.total_energy_kwh).label('total_kwh'),
                    func.sum(DailyEnergyView.total_cost).label('total_cost'),
                )
                .filter(DailyEnergyView.date >= month_start)
                .first()
            )
            total_kwh  = float(rows.total_kwh  or 0)
            total_cost = float(rows.total_cost or 0)
            return {
                'total_kwh':  round(total_kwh, 2),
                'total_cost': round(total_cost, 0),
            }
        except Exception as e:
            logger.error(f"get_header_stats error: {e}", exc_info=True)
            return {'total_kwh': 0, 'total_cost': 0}
        finally:
            db.close()

    # ── Main Grid: kartu per building ─────────────────────────────────────────

    def get_building_cards(self) -> list:
        """
        Data per building: sensor realtime + energi hari ini & bulan ini + alarm aktif.

        Returns list of dict:
            building_id, building_name,
            sensors: [ {phase, voltage, current, power} ],
            energy_today_kwh, energy_month_kwh,
            alarm_count, alarm_status ('normal'|'warning'|'critical')
        """
        db = get_session()
        try:
            realtime = _realtime_all()
            today    = date.today()
            month_start = today.replace(day=1)

            buildings = db.query(Building).order_by(Building.id).all()
            results   = []

            for bld in buildings:
                sensors = (
                    db.query(Sensor)
                    .filter(Sensor.building_id == bld.id)
                    .order_by(Sensor.name)
                    .all()
                )
                sensor_ids = [s.id for s in sensors]

                # ── Realtime per fasa ──────────────────────────────────────
                sensor_rows = []
                dept = realtime.get(f"department{bld.id}", {})

                for s in sensors:
                    rt = dept.get(s.phase) or {}

                    sensor_rows.append({
                        'phase':   s.phase or s.name,
                        'voltage': round(float(rt.get('voltage', 0)), 1),
                        'current': round(float(rt.get('current', 0)), 1),
                        'power':   round(float(rt.get('power',   0)), 1),
                    })

                # ── Energi hari ini ────────────────────────────────────────
                day_rows = (
                    db.query(
                        func.sum(HourlyEnergyView.total_kwh).label('kwh'),
                    )
                    .filter(
                        HourlyEnergyView.sensor_id.in_(sensor_ids),
                        func.date(HourlyEnergyView.date) == today,
                    )
                    .first()
                )
                energy_today = float(day_rows.kwh or 0)

                # ── Energi bulan ini ───────────────────────────────────────
                month_rows = (
                    db.query(func.sum(DailyEnergyView.total_energy_kwh))
                    .filter(
                        DailyEnergyView.sensor_id.in_(sensor_ids),
                        DailyEnergyView.date >= month_start,
                    )
                    .scalar()
                )
                energy_month = float(month_rows or 0)

                # ── Alarm aktif ────────────────────────────────────────────
                active_alarms = (
                    db.query(AlarmEvent)
                    .join(Sensor, AlarmEvent.sensor_id == Sensor.id)
                    .filter(
                        Sensor.building_id == bld.id,
                        AlarmEvent.is_normal == False,
                    )
                    .order_by(AlarmEvent.timestamp.desc())
                    .all()
                )

                alarm_count = len(active_alarms)
                if alarm_count == 0:
                    alarm_status = 'normal'
                else:
                    severities = [a.get_severity() for a in active_alarms]
                    alarm_status = 'critical' if 'critical' in severities else 'warning'

                results.append({
                    'building_id':       bld.id,
                    'building_name':     bld.name,
                    'sensors':           sensor_rows,
                    'energy_today_kwh':  round(energy_today, 2),
                    'energy_month_kwh':  round(energy_month, 2),
                    'alarm_count':       alarm_count,
                    'alarm_status':      alarm_status,
                    'alarms':            [
                        {
                            'parameter':    a.parameter,
                            'actual_value': float(a.actual_value or 0),
                            'status':       a.get_status_display(),
                            'timestamp':    a.timestamp.strftime('%H:%M:%S'),
                        }
                        for a in active_alarms[:3]  # maks 3 alarm per building
                    ],
                })

            return results

        except Exception as e:
            logger.error(f"get_building_cards error: {e}", exc_info=True)
            return []
        finally:
            db.close()

    # ── Summary: alarm aktif global ───────────────────────────────────────────

    def get_active_alarms(self) -> list:
        """
        Semua alarm aktif lintas building untuk panel alarm kanan.
        """
        db = get_session()
        try:
            alarms = (
                db.query(AlarmEvent, Sensor, Building)
                .join(Sensor,   AlarmEvent.sensor_id   == Sensor.id)
                .join(Building, Sensor.building_id     == Building.id)
                .filter(AlarmEvent.is_normal == False)
                .order_by(AlarmEvent.timestamp.desc())
                .limit(10)
                .all()
            )
            return [
                {
                    'building_name': bld.name,
                    'parameter':     a.parameter,
                    'actual_value':  float(a.actual_value or 0),
                    'status':        a.get_status_display(),
                    'severity':      a.get_severity(),
                    'timestamp':     a.timestamp.strftime('%H:%M:%S'),
                    'threshold_min': float(a.threshold_min) if a.threshold_min else None,
                    'threshold_max': float(a.threshold_max) if a.threshold_max else None,
                }
                for a, s, bld in alarms
            ]
        except Exception as e:
            logger.error(f"get_active_alarms error: {e}", exc_info=True)
            return []
        finally:
            db.close()

    # ── Summary: keseimbangan fasa ────────────────────────────────────────────

    def get_phase_balance(self) -> list:
        db = get_session()
        try:
            today = date.today()

            buildings = db.query(Building).order_by(Building.id).all()
            results = []

            for bld in buildings:
                sensors = (
                    db.query(Sensor)
                    .filter(Sensor.building_id == bld.id)
                    .all()
                )

                phase_current = {'R': 0.0, 'S': 0.0, 'T': 0.0}

                for s in sensors:
                    ph = (s.phase or 'R').strip().upper()

                    # 🔥 agregasi dari hourly
                    avg_current = (
                        db.query(func.avg(HourlyEnergyView.avg_current))
                        .filter(
                            HourlyEnergyView.sensor_id == s.id,
                            func.date(HourlyEnergyView.date) == today
                        )
                        .scalar()
                    )

                    if ph in phase_current:
                        phase_current[ph] = round(float(avg_current or 0), 2)

                vals = list(phase_current.values())
                max_v = max(vals) if vals else 0
                min_v = min(vals) if vals else 0

                imbalance_pct = round((max_v - min_v) / max_v * 100, 1) if max_v > 0 else 0

                results.append({
                    'building_name':  bld.name,
                    'phase_R':        phase_current['R'],
                    'phase_S':        phase_current['S'],
                    'phase_T':        phase_current['T'],
                    'imbalance_pct':  imbalance_pct,
                    'is_ok':          imbalance_pct < 5.0,
                })

            return results

        except Exception as e:
            logger.error(f"get_phase_balance error: {e}", exc_info=True)
            return []
        finally:
            db.close()

    # ── Summary: distribusi beban ─────────────────────────────────────────────

    def get_load_distribution(self) -> dict:
        db = get_session()
        try:
            today = date.today()

            start = datetime.combine(today, datetime.min.time())
            end   = datetime.combine(today, datetime.max.time())

            rows = (
                db.query(
                    Building.name.label('building_name'),
                    func.sum(HourlyEnergyView.total_kwh).label('kwh'),
                )
                .join(Sensor, Building.id == Sensor.building_id)
                .join(HourlyEnergyView, Sensor.id == HourlyEnergyView.sensor_id)
                .filter(
                    HourlyEnergyView.date >= start,
                    HourlyEnergyView.date <= end
                )
                .group_by(Building.id, Building.name)
                .order_by(func.sum(HourlyEnergyView.total_kwh).desc())
                .all()
            )

            buildings = [
                {'name': r.building_name, 'kwh': round(float(r.kwh or 0), 2)}
                for r in rows
            ]

            total   = sum(b['kwh'] for b in buildings)
            max_kwh = buildings[0]['kwh'] if buildings else 1
            top_pct = round(buildings[0]['kwh'] / total * 100, 1) if total > 0 else 0

            return {
                'buildings': buildings,
                'total_kwh': round(total, 2),
                'max_kwh':   max_kwh,
                'top_name':  buildings[0]['name'] if buildings else '-',
                'top_pct':   top_pct,
            }

        except Exception as e:
            logger.error(f"get_load_distribution error: {e}", exc_info=True)
            return {
                'buildings': [],
                'total_kwh': 0,
                'max_kwh': 1,
                'top_name': '-',
                'top_pct': 0
            }
        finally:
            db.close()