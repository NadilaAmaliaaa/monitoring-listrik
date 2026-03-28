# controllers/analytics_controller.py
"""
AnalyticsController — data untuk halaman Analytics Tren Energi.

Sumber data:
  - view_daily_energy  : konsumsi harian per sensor (DailyEnergyView)
  - view_hourly_energy : konsumsi per jam per sensor (HourlyEnergyView)
  - sensor_readings    : data mentah untuk power factor history
"""
import logging
from datetime import datetime, date, timedelta
from sqlalchemy import func
from database import get_session
from models.data import Sensor, SensorReading
from models.views import DailyEnergyView, HourlyEnergyView

logger = logging.getLogger(__name__)


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

    def get_summary_cards(self, days: int = 7) -> dict:
        """
        Kartu ringkasan atas halaman analytics.
        Returns:
            total_kwh, peak_power (kW), peak_datetime, avg_pf, total_cost
        """
        db = get_session()
        try:
            since = date.today() - timedelta(days=days)
            sensor_ids = self._sensor_ids(db)
            if not sensor_ids:
                return self._empty_cards()

            rows = (
                db.query(DailyEnergyView)
                .filter(
                    DailyEnergyView.sensor_id.in_(sensor_ids),
                    DailyEnergyView.date >= since,
                )
                .all()
            )

            if not rows:
                return self._empty_cards()

            total_kwh  = sum(r.total_energy_kwh or 0 for r in rows)
            total_cost = sum(r.total_cost       or 0 for r in rows)
            peak_power = max(r.peak_power or 0 for r in rows)
            pf_values  = [r.avg_pf for r in rows if r.avg_pf is not None]
            avg_pf     = sum(pf_values) / len(pf_values) if pf_values else 0

            # Cari tanggal peak
            peak_row      = max(rows, key=lambda r: r.peak_power or 0)
            peak_datetime = str(peak_row.date) if peak_row else '-'

            # Bandingkan dengan periode sebelumnya untuk persentase perubahan
            prev_since = since - timedelta(days=days)
            prev_rows  = (
                db.query(DailyEnergyView)
                .filter(
                    DailyEnergyView.sensor_id.in_(sensor_ids),
                    DailyEnergyView.date >= prev_since,
                    DailyEnergyView.date < since,
                )
                .all()
            )
            prev_kwh  = sum(r.total_energy_kwh or 0 for r in prev_rows)
            kwh_delta = ((total_kwh - prev_kwh) / prev_kwh * 100) if prev_kwh else 0

            return {
                'total_kwh':     round(total_kwh, 2),
                'peak_power_kw': round(peak_power / 1000, 2),  # watt → kW
                'peak_datetime': peak_datetime,
                'avg_pf':        round(avg_pf, 3),
                'total_cost':    round(total_cost, 0),
                'kwh_delta_pct': round(kwh_delta, 1),
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

    # ── Tren Konsumsi Energi ──────────────────────────────────────────────────

    def get_energy_trend(self, period: str = 'daily', days: int = 7) -> dict:
        """
        Data tren konsumsi energi per fasa (R/S/T) untuk chart batang.

        period: 'daily' | 'hourly'
        Returns:
            labels    : list tanggal/jam
            series    : { 'R': [...], 'S': [...], 'T': [...] }
            unit      : 'kWh'
        """
        db = get_session()
        try:
            sensors   = self._get_sensors(db)
            phase_map = {s.id: s.phase for s in sensors}  # sensor_id → phase (R/S/T)

            from collections import defaultdict
            date_phase: dict = defaultdict(lambda: {'R': 0.0, 'S': 0.0, 'T': 0.0})

            if period == 'hourly':
                # Data per jam — 24 jam terakhir
                since = date.today() - timedelta(days=1)
                rows  = (
                    db.query(HourlyEnergyView)
                    .filter(
                        HourlyEnergyView.sensor_id.in_(list(phase_map.keys())),
                        HourlyEnergyView.date >= since,
                    )
                    .order_by(HourlyEnergyView.date)
                    .all()
                )
                for r in rows:
                    phase = phase_map.get(r.sensor_id, 'R')
                    label = str(r.date)
                    date_phase[label][phase] += r.total_kwh or 0

            elif period == 'monthly':
                # Data per bulan — seluruh tahun berjalan (Jan s/d bulan ini)
                year_start = date(date.today().year, 1, 1)
                rows = (
                    db.query(DailyEnergyView)
                    .filter(
                        DailyEnergyView.sensor_id.in_(list(phase_map.keys())),
                        DailyEnergyView.date >= year_start,
                    )
                    .order_by(DailyEnergyView.date)
                    .all()
                )
                for r in rows:
                    phase = phase_map.get(r.sensor_id, 'R')
                    # Kelompokkan per nama bulan
                    label = r.date.strftime('%b %Y')
                    date_phase[label][phase] += r.total_energy_kwh or 0

                # Pastikan semua bulan Jan–bulan_ini ada (meskipun kosong)
                today = date.today()
                for m in range(1, today.month + 1):
                    lbl = date(today.year, m, 1).strftime('%b %Y')
                    if lbl not in date_phase:
                        date_phase[lbl] = {'R': 0.0, 'S': 0.0, 'T': 0.0}

            else:
                # Daily — 30 hari terakhir
                since = date.today() - timedelta(days=days)
                rows  = (
                    db.query(DailyEnergyView)
                    .filter(
                        DailyEnergyView.sensor_id.in_(list(phase_map.keys())),
                        DailyEnergyView.date >= since,
                    )
                    .order_by(DailyEnergyView.date)
                    .all()
                )
                for r in rows:
                    phase = phase_map.get(r.sensor_id, 'R')
                    label = r.date.strftime('%d %b')
                    date_phase[label][phase] += r.total_energy_kwh or 0

            # Sort label: untuk monthly urutkan berdasarkan bulan, lainnya sudah string sort
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
        """
        Arus rata-rata per fasa per hari untuk chart keseimbangan.
        Returns:
            labels  : list tanggal
            series  : { 'R': [...], 'S': [...], 'T': [...] }
            unit    : 'A'
            status  : 'balanced' | 'unbalanced'
        """
        db = get_session()
        try:
            sensors   = self._get_sensors(db)
            phase_map = {s.id: s.phase for s in sensors}
            since     = date.today() - timedelta(days=days)

            rows = (
                db.query(DailyEnergyView)
                .filter(
                    DailyEnergyView.sensor_id.in_(list(phase_map.keys())),
                    DailyEnergyView.date >= since,
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

            # Status seimbang jika selisih antar fasa < 10%
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
        """
        Peak power (kW) per hari selama N hari terakhir.
        Returns:
            labels      : list tanggal
            values      : list peak kW
            avg_peak_kw : rata-rata
            growth_pct  : persentase growth vs periode sebelumnya
        """
        db = get_session()
        try:
            sensor_ids = self._sensor_ids(db)
            since      = date.today() - timedelta(days=days)

            rows = (
                db.query(
                    DailyEnergyView.date,
                    func.max(DailyEnergyView.peak_power).label('peak')
                )
                .filter(
                    DailyEnergyView.sensor_id.in_(sensor_ids),
                    DailyEnergyView.date >= since,
                )
                .group_by(DailyEnergyView.date)
                .order_by(DailyEnergyView.date)
                .all()
            )

            labels = [r.date.strftime('%d %b') for r in rows]
            values = [round((r.peak or 0) / 1000, 2) for r in rows]  # W → kW
            avg    = round(sum(values) / len(values), 2) if values else 0

            # Growth vs 7 hari sebelumnya
            prev_since = since - timedelta(days=days)
            prev_rows  = (
                db.query(func.max(DailyEnergyView.peak_power))
                .filter(
                    DailyEnergyView.sensor_id.in_(sensor_ids),
                    DailyEnergyView.date >= prev_since,
                    DailyEnergyView.date < since,
                )
                .scalar()
            )
            curr_max  = max(values) if values else 0
            prev_max  = (prev_rows or 0) / 1000
            growth    = round((curr_max - prev_max) / prev_max * 100, 1) if prev_max else 0

            return {
                'labels':       labels,
                'values':       values,
                'avg_peak_kw':  avg,
                'growth_pct':   growth,
            }
        except Exception as e:
            logger.error(f"get_peak_load_trend error: {e}", exc_info=True)
            return {'labels': [], 'values': [], 'avg_peak_kw': 0, 'growth_pct': 0}
        finally:
            db.close()

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
            since      = date.today() - timedelta(days=days)

            rows = (
                db.query(
                    DailyEnergyView.date,
                    func.avg(DailyEnergyView.avg_pf).label('avg_pf')
                )
                .filter(
                    DailyEnergyView.sensor_id.in_(sensor_ids),
                    DailyEnergyView.date >= since,
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