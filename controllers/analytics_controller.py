# controllers/analytics_controller.py
import logging
from datetime import datetime, date, timedelta, timezone
from sqlalchemy import func
from database import get_session
from models.data import Sensor, SensorReading
from models.views import DailyEnergyView, HourlyEnergyView

logger = logging.getLogger(__name__)

# ── Timezone WIB (UTC+7) — dipakai konsisten di seluruh controller ────────────
_WIB = timezone(timedelta(hours=7))


def _today_wib() -> date:
    """Tanggal hari ini dalam WIB — konsisten dengan data lokal."""
    return datetime.now(_WIB).date()


def _month_start_wib() -> date:
    """Tanggal awal bulan ini dalam WIB."""
    return _today_wib().replace(day=1)


def _tomorrow_wib() -> date:
    """Besok dalam WIB — dipakai sebagai exclusive upper bound filter."""
    return _today_wib() + timedelta(days=1)


# ── Shorthand filter helpers ──────────────────────────────────────────────────
# Karena kolom date di view bertipe timestamptz, cast eksplisit ke date
# diperlukan agar perbandingan tidak bergantung pada session timezone PostgreSQL.

def _date_col(col):
    """Cast kolom timestamptz ke date (pakai timezone Asia/Jakarta)."""
    return func.date(func.timezone('Asia/Jakarta', col))


class AnalyticsController:

    def __init__(self, building_id: int):
        self.building_id = building_id

    # ── Helper ────────────────────────────────────────────────────────────────

    def _get_sensors(self, db):
        """Ambil semua sensor milik building ini."""
        return (
            db.query(Sensor)
            .filter(Sensor.building_id == self.building_id)
            .order_by(Sensor.name)
            .all()
        )

    def _sensor_ids(self, db):
        return [s.id for s in self._get_sensors(db)]

    # ── Stats Cards ───────────────────────────────────────────────────────────

    def get_summary_cards(self) -> dict:
        db = get_session()
        try:
            today    = _today_wib()
            tomorrow = _tomorrow_wib()

            # Bulan ini: [start_date, end_date)
            start_date = today.replace(day=1)
            end_date   = (start_date + timedelta(days=32)).replace(day=1)

            # Bulan sebelumnya
            prev_start_date = (start_date - timedelta(days=1)).replace(day=1)
            prev_end_date   = start_date

            sensor_ids = self._sensor_ids(db)
            if not sensor_ids:
                return self._empty_cards()

            # Total energi bulan ini
            total_kwh = (
                db.query(func.sum(DailyEnergyView.total_energy_kwh))
                .filter(
                    DailyEnergyView.sensor_id.in_(sensor_ids),
                    _date_col(DailyEnergyView.date) >= start_date,
                    _date_col(DailyEnergyView.date) <  end_date,
                )
                .scalar()
            ) or 0

            total_cost = (
                db.query(func.sum(DailyEnergyView.total_cost))
                .filter(
                    DailyEnergyView.sensor_id.in_(sensor_ids),
                    _date_col(DailyEnergyView.date) >= start_date,
                    _date_col(DailyEnergyView.date) <  end_date,
                )
                .scalar()
            ) or 0

            # Total energi bulan sebelumnya
            prev_total_kwh = (
                db.query(func.sum(DailyEnergyView.total_energy_kwh))
                .filter(
                    DailyEnergyView.sensor_id.in_(sensor_ids),
                    _date_col(DailyEnergyView.date) >= prev_start_date,
                    _date_col(DailyEnergyView.date) <  prev_end_date,
                )
                .scalar()
            ) or 0

            # Delta (%)
            if prev_total_kwh > 0:
                kwh_delta_pct = ((total_kwh - prev_total_kwh) / prev_total_kwh) * 100
            else:
                kwh_delta_pct = 0

            # Data untuk peak & PF
            rows = (
                db.query(DailyEnergyView)
                .filter(
                    DailyEnergyView.sensor_id.in_(sensor_ids),
                    _date_col(DailyEnergyView.date) >= start_date,
                    _date_col(DailyEnergyView.date) <  end_date,
                )
                .all()
            )

            if not rows:
                return self._empty_cards()

            peak_row = (
                db.query(
                    DailyEnergyView.date,
                    func.sum(DailyEnergyView.peak_power).label('total_peak')
                )
                .filter(
                    DailyEnergyView.sensor_id.in_(sensor_ids),
                    _date_col(DailyEnergyView.date) >= start_date,
                    _date_col(DailyEnergyView.date) <  end_date,
                )
                .group_by(DailyEnergyView.date)
                .order_by(func.sum(DailyEnergyView.peak_power).desc())
                .first()
            )
            peak_power = peak_row.total_peak or 0

            pf_values = [r.avg_pf for r in rows if r.avg_pf is not None]
            avg_pf    = sum(pf_values) / len(pf_values) if pf_values else 0

            return {
                'total_kwh':        round(total_kwh, 2),
                'peak_power_kw':    round(peak_power / 1000, 2),
                'peak_datetime':    str(peak_row.date),
                'avg_pf':           round(avg_pf, 3),
                'total_cost':       round(total_cost, 0),
                'kwh_delta_pct':    round(kwh_delta_pct, 1),
                'last_month_kwh':   round(prev_total_kwh, 2),
                'last_month_start': str(prev_start_date),
                'last_month_end':   str(prev_end_date - timedelta(days=1)),
            }

        except Exception as e:
            logger.error(f"get_summary_cards error: {e}", exc_info=True)
            return self._empty_cards()
        finally:
            db.close()

    def _empty_cards(self):
        return {
            'total_kwh': 0, 'peak_power_kw': 0, 'peak_datetime': '-',
            'avg_pf': 0, 'total_cost': 0, 'kwh_delta_pct': 0,
        }

    # ── Monthly Energy ────────────────────────────────────────────────────────

    def get_monthly_energy(self) -> dict:
        db = get_session()
        try:
            sensor_ids = self._sensor_ids(db)
            today      = _today_wib()
            tomorrow   = _tomorrow_wib()
            since      = _month_start_wib()

            if not sensor_ids:
                return {'total_kwh': 0, 'since': str(since), 'until': str(today)}

            total = (
                db.query(func.sum(DailyEnergyView.total_energy_kwh))
                .filter(
                    DailyEnergyView.sensor_id.in_(sensor_ids),
                    _date_col(DailyEnergyView.date) >= since,
                    _date_col(DailyEnergyView.date) <  tomorrow,
                )
                .scalar()
            ) or 0

            return {
                'total_kwh': round(float(total), 2),
                'since':     str(since),
                'until':     str(today),
            }
        except Exception as e:
            logger.error(f"get_monthly_energy error: {e}", exc_info=True)
            return {'total_kwh': 0, 'since': '', 'until': ''}
        finally:
            db.close()

    # ── Tren Konsumsi Energi ──────────────────────────────────────────────────

    def get_energy_trend(self, period: str = 'daily', days: int = 7) -> dict:
        """
        Data tren konsumsi energi per fasa (R/S/T) untuk chart batang.

        period : 'daily' | 'hourly' | 'monthly'
        days   : rentang hari untuk mode 'daily'

        Returns:
            labels  : list tanggal/jam
            series  : { 'R': [...], 'S': [...], 'T': [...] }
            unit    : 'kWh'
        """
        db = get_session()
        try:
            sensors   = self._get_sensors(db)
            phase_map = {s.id: s.phase for s in sensors}

            from collections import defaultdict
            date_phase: dict = defaultdict(lambda: {'R': 0.0, 'S': 0.0, 'T': 0.0})

            today    = _today_wib()
            tomorrow = _tomorrow_wib()

            if period == 'hourly':
                now   = datetime.now(_WIB)
                since = now.replace(hour=0, minute=0, second=0, microsecond=0)

                rows = (
                    db.query(HourlyEnergyView)
                    .filter(
                        HourlyEnergyView.sensor_id.in_(list(phase_map.keys())),
                        HourlyEnergyView.date >= since,
                        HourlyEnergyView.date <= now,
                    )
                    .order_by(HourlyEnergyView.date)
                    .all()
                )

                for r in rows:
                    phase = phase_map.get(r.sensor_id, 'R')
                    label = r.date.strftime('%H:%M')
                    date_phase[label][phase] += r.total_kwh or 0

            elif period == 'monthly':
                year_start = date(today.year, 1, 1)
                rows = (
                    db.query(DailyEnergyView)
                    .filter(
                        DailyEnergyView.sensor_id.in_(list(phase_map.keys())),
                        _date_col(DailyEnergyView.date) >= year_start,
                        _date_col(DailyEnergyView.date) <  tomorrow,
                    )
                    .order_by(DailyEnergyView.date)
                    .all()
                )
                for r in rows:
                    phase = phase_map.get(r.sensor_id, 'R')
                    label = r.date.strftime('%b %Y')
                    date_phase[label][phase] += r.total_energy_kwh or 0

                for m in range(1, today.month + 1):
                    lbl = date(today.year, m, 1).strftime('%b %Y')
                    if lbl not in date_phase:
                        date_phase[lbl] = {'R': 0.0, 'S': 0.0, 'T': 0.0}

            else:
                # Daily — [awal bulan, besok)
                start_date = today.replace(day=1)
                rows = (
                    db.query(DailyEnergyView)
                    .filter(
                        DailyEnergyView.sensor_id.in_(list(phase_map.keys())),
                        _date_col(DailyEnergyView.date) >= start_date,
                        _date_col(DailyEnergyView.date) <  tomorrow,
                    )
                    .order_by(DailyEnergyView.date)
                    .all()
                )
                for r in rows:
                    phase = phase_map.get(r.sensor_id, 'R')
                    label = r.date.strftime('%d %b')
                    date_phase[label][phase] += r.total_energy_kwh or 0

            if period == 'monthly':
                labels = sorted(date_phase.keys(),
                                key=lambda s: datetime.strptime(s, '%b %Y'))
            else:
                labels = sorted(date_phase.keys())

            return {
                'labels': labels,
                'series': {
                    'R': [round(date_phase[l]['R'], 2) for l in labels],
                    'S': [round(date_phase[l]['S'], 2) for l in labels],
                    'T': [round(date_phase[l]['T'], 2) for l in labels],
                },
                'unit': 'kWh',
            }
        except Exception as e:
            logger.error(f"get_energy_trend error: {e}", exc_info=True)
            return {'labels': [], 'series': {'R': [], 'S': [], 'T': []}, 'unit': 'kWh'}
        finally:
            db.close()

    # ── Keseimbangan Fasa ─────────────────────────────────────────────────────

    def get_phase_balance(self, days: int = 7) -> dict:
        db = get_session()
        try:
            sensors   = self._get_sensors(db)
            phase_map = {s.id: s.phase for s in sensors}

            today      = _today_wib()
            tomorrow   = _tomorrow_wib()
            start_date = today.replace(day=1)

            rows = (
                db.query(DailyEnergyView)
                .filter(
                    DailyEnergyView.sensor_id.in_(list(phase_map.keys())),
                    _date_col(DailyEnergyView.date) >= start_date,
                    _date_col(DailyEnergyView.date) <  tomorrow,
                )
                .order_by(DailyEnergyView.date)
                .all()
            )

            from collections import defaultdict
            date_phase = defaultdict(lambda: {'R': [], 'S': [], 'T': []})

            for r in rows:
                phase = phase_map.get(r.sensor_id, 'R')
                label = r.date.strftime('%d %b')
                if r.total_current is not None:
                    date_phase[label][phase].append(r.total_current)

            labels = sorted(date_phase.keys())
            series = {
                ph: [
                    round(sum(date_phase[l][ph]) / len(date_phase[l][ph]), 2)
                    if date_phase[l][ph] else 0
                    for l in labels
                ]
                for ph in ('R', 'S', 'T')
            }

            status = 'balanced'
            for i, label in enumerate(labels):
                vals = [series[ph][i] for ph in ('R', 'S', 'T') if series[ph][i] > 0]
                if vals and (max(vals) - min(vals)) / max(vals) > 0.10:
                    status = 'unbalanced'
                    break

            return {'labels': labels, 'series': series, 'unit': 'A', 'status': status}
        except Exception as e:
            logger.error(f"get_phase_balance error: {e}", exc_info=True)
            return {'labels': [], 'series': {'R': [], 'S': [], 'T': []}, 'unit': 'A', 'status': 'balanced'}
        finally:
            db.close()

    # ── Peak Load Trend ───────────────────────────────────────────────────────

    def get_peak_load_trend(self, days: int = 7) -> dict:
        db = get_session()
        try:
            sensor_ids = self._sensor_ids(db)
            if not sensor_ids:
                return self._empty_peak_response()

            today    = _today_wib()
            tomorrow = _tomorrow_wib()

            # Periode saat ini (month-to-date): [start_date, tomorrow)
            start_date = today.replace(day=1)

            # Periode sebelumnya (day-aligned)
            prev_start_date = (start_date - timedelta(days=1)).replace(day=1)
            prev_end_date   = start_date

            # Data periode saat ini
            rows = (
                db.query(
                    DailyEnergyView.date,
                    func.sum(DailyEnergyView.peak_power).label('peak_w'),
                    func.sum(DailyEnergyView.avg_power).label('avg_w'),
                )
                .filter(
                    DailyEnergyView.sensor_id.in_(sensor_ids),
                    _date_col(DailyEnergyView.date) >= start_date,
                    _date_col(DailyEnergyView.date) <  tomorrow,
                )
                .group_by(DailyEnergyView.date)
                .order_by(DailyEnergyView.date)
                .all()
            )

            labels       = [r.date.strftime('%d %b') for r in rows]
            values       = [(r.peak_w or 0) / 1000 for r in rows]
            daily_avg_kw = [(r.avg_w or 0) / 1000 for r in rows]
            curr_avg     = sum(daily_avg_kw) / len(daily_avg_kw) if daily_avg_kw else 0

            # Data periode sebelumnya
            prev_rows = (
                db.query(
                    DailyEnergyView.date,
                    func.sum(DailyEnergyView.avg_power).label('avg_w'),
                )
                .filter(
                    DailyEnergyView.sensor_id.in_(sensor_ids),
                    _date_col(DailyEnergyView.date) >= prev_start_date,
                    _date_col(DailyEnergyView.date) <  prev_end_date,
                )
                .group_by(DailyEnergyView.date)
                .order_by(DailyEnergyView.date)
                .all()
            )

            prev_daily_avg_kw = [(r.avg_w or 0) / 1000 for r in prev_rows]
            prev_avg = (
                sum(prev_daily_avg_kw) / len(prev_daily_avg_kw)
                if prev_daily_avg_kw else 0
            )

            growth = ((curr_avg - prev_avg) / prev_avg * 100) if prev_avg > 0 else 0

            return {
                'labels':            labels,
                'values':            [round(v, 2) for v in values],
                'avg_power_kw':      round(curr_avg, 2),
                'prev_avg_power_kw': round(prev_avg, 2),
                'growth_pct':        round(growth, 1),
                'current_month':     start_date.strftime('%b %Y'),
                'previous_month':    prev_start_date.strftime('%b %Y'),
            }

        except Exception as e:
            logger.error(f"get_peak_load_trend error: {e}", exc_info=True)
            return self._empty_peak_response()
        finally:
            db.close()

    def _empty_peak_response(self):
        return {
            'labels': [], 'values': [],
            'avg_power_kw': 0, 'prev_avg_power_kw': 0,
            'growth_pct': 0, 'current_month': '', 'previous_month': '',
        }

    # ── Power Factor History ──────────────────────────────────────────────────

    def get_pf_history(self, days: int = 7) -> dict:
        """
        Rata-rata power factor harian untuk line chart.

        Returns:
            labels    : list tanggal
            values    : list avg PF
            threshold : 0.85
        """
        db = get_session()
        try:
            sensor_ids = self._sensor_ids(db)
            today      = _today_wib()
            tomorrow   = _tomorrow_wib()
            since      = today - timedelta(days=days)

            rows = (
                db.query(
                    DailyEnergyView.date,
                    func.avg(DailyEnergyView.avg_pf).label('avg_pf')
                )
                .filter(
                    DailyEnergyView.sensor_id.in_(sensor_ids),
                    _date_col(DailyEnergyView.date) >= since,
                    _date_col(DailyEnergyView.date) <  tomorrow,
                )
                .group_by(DailyEnergyView.date)
                .order_by(DailyEnergyView.date)
                .all()
            )

            labels = [r.date.strftime('%d %b') for r in rows]
            values = [round(float(r.avg_pf or 0), 3) for r in rows]

            return {
                'labels':    labels,
                'values':    values,
                'threshold': 0.85,
            }
        except Exception as e:
            logger.error(f"get_pf_history error: {e}", exc_info=True)
            return {'labels': [], 'values': [], 'threshold': 0.85}
        finally:
            db.close()