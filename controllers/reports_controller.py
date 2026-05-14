# controllers/reports_controller.py
from datetime import datetime, timedelta, date
from collections import defaultdict
from sqlalchemy import func, text
from models.views import HourlyEnergyView, DailyEnergyView
from models.data import Sensor
from models.building import Building
import csv
import io
import math

# ReportLab
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm, mm
from reportlab.graphics.shapes import Drawing, Rect, Line, String, Polygon
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics import renderPDF
from reportlab.graphics.widgets.markers import makeMarker
from flask import send_file

# ── Warna brand ───────────────────────────────────────────────────────────────
C_PRIMARY   = colors.HexColor('#136dec')
C_DARK      = colors.HexColor('#0f172a')
C_SLATE     = colors.HexColor('#64748b')
C_LIGHT     = colors.HexColor('#f8fafc')
C_BORDER    = colors.HexColor('#e2e8f0')
C_SUCCESS   = colors.HexColor('#059669')
C_WARNING   = colors.HexColor('#d97706')
C_DANGER    = colors.HexColor('#dc2626')
C_PHASE_R   = colors.HexColor('#ef4444')
C_PHASE_S   = colors.HexColor('#eab308')
C_PHASE_T   = colors.HexColor('#3b82f6')
C_ROW_ODD   = colors.HexColor('#f8fafc')
C_ROW_EVEN  = colors.white
C_HDR_BG    = colors.HexColor('#1e3a5f')


def _pct_change(new, old):
    if not old:
        return None
    return round((new - old) / old * 100, 1)


def _fmt_num(v, dec=2):
    if v is None:
        return '—'
    return f"{v:,.{dec}f}"


def _fmt_rp(v):
    if v is None:
        return '—'
    if v >= 1_000_000:
        return f"Rp {v/1_000_000:,.2f} Jt"
    return f"Rp {v:,.0f}"


def _trend_arrow(pct):
    """Return text arrow and color for trend."""
    if pct is None:
        return '—', C_SLATE
    if pct > 0:
        return f'▲ {abs(pct):.1f}%', C_DANGER
    if pct < 0:
        return f'▼ {abs(pct):.1f}%', C_SUCCESS
    return '= 0%', C_SLATE


# ── Mini sparkline chart (ReportLab Drawing) ──────────────────────────────────
def _mini_line_chart(data_r, data_s, data_t, w=160, h=60):
    """Buat sparkline tren 3 fasa sebagai ReportLab Drawing."""
    d  = Drawing(w, h)
    pad = 8

    all_vals = [v for v in data_r + data_s + data_t if v is not None]
    if not all_vals:
        d.add(String(w/2, h/2, 'Tidak ada data', fontSize=7,
                     fillColor=C_SLATE, textAnchor='middle'))
        return d

    mn = min(all_vals)
    mx = max(all_vals)
    rng = mx - mn or 1

    def _y(v):
        return pad + ((v - mn) / rng) * (h - 2 * pad)

    def _x(i, n):
        return pad + (i / max(n - 1, 1)) * (w - 2 * pad)

    for dataset, col in [(data_r, C_PHASE_R), (data_s, C_PHASE_S), (data_t, C_PHASE_T)]:
        pts = [(i, v) for i, v in enumerate(dataset) if v is not None]
        for j in range(len(pts) - 1):
            i1, v1 = pts[j]
            i2, v2 = pts[j + 1]
            d.add(Line(
                _x(i1, len(dataset)), _y(v1),
                _x(i2, len(dataset)), _y(v2),
                strokeColor=col, strokeWidth=1.5
            ))

    return d


class ReportsController:
    def __init__(self, session, building_id=None):
        self.session  = session
        self.building_id = building_id

    def _get_base_query_filter(self, query):
        if self.building_id:
            query = query.filter(Sensor.building_id == self.building_id)
        return query

    # ── History table (for web page) ─────────────────────────────────────────

    def get_history(self, page=1, per_page=10, period='hourly'):
        offset    = (page - 1) * per_page
        now       = datetime.utcnow()

        if period == 'hourly':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date   = start_date + timedelta(days=1)
            query = (
                self.session.query(
                    HourlyEnergyView.date,
                    Sensor.phase,
                    HourlyEnergyView.avg_power,
                    HourlyEnergyView.peak_power,
                    HourlyEnergyView.total_kwh,
                )
                .join(Sensor, Sensor.id == HourlyEnergyView.sensor_id)
                .filter(HourlyEnergyView.date >= start_date,
                        HourlyEnergyView.date < end_date)
            )
            query = self._get_base_query_filter(query)
            query = query.order_by(HourlyEnergyView.date.desc())

        elif period == 'daily':
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            query = (
                self.session.query(
                    DailyEnergyView.date,
                    Sensor.phase,
                    DailyEnergyView.avg_power,
                    DailyEnergyView.peak_power,
                    DailyEnergyView.total_energy_kwh,
                )
                .join(Sensor, Sensor.id == DailyEnergyView.sensor_id)
                .filter(DailyEnergyView.date >= start_date,
                        DailyEnergyView.date <= now)
            )
            query = self._get_base_query_filter(query)
            query = query.order_by(DailyEnergyView.date.desc())

        else:  # monthly
            start_date = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            query = (
                self.session.query(
                    func.date_trunc('month', DailyEnergyView.date).label('date'),
                    Sensor.phase,
                    func.avg(DailyEnergyView.avg_power).label('avg_power'),
                    func.max(DailyEnergyView.peak_power).label('peak_power'),
                    func.sum(DailyEnergyView.total_energy_kwh).label('total_kwh'),
                )
                .join(Sensor, Sensor.id == DailyEnergyView.sensor_id)
                .filter(DailyEnergyView.date >= start_date,
                        DailyEnergyView.date <= now)
            )
            query = self._get_base_query_filter(query)
            query = query.group_by(
                func.date_trunc('month', DailyEnergyView.date), Sensor.phase
            ).order_by(text('date DESC'))

        total   = query.count()
        results = query.offset(offset).limit(per_page).all()

        if period == 'hourly':
            data = [{'date': r.date.strftime('%H:%M'), 'phase': r.phase,
                     'avg_power': float(r.avg_power or 0),
                     'peak_power': float(r.peak_power or 0),
                     'total_kwh': float(r.total_kwh or 0)} for r in results]
        elif period == 'daily':
            data = [{'date': r.date.strftime('%Y-%m-%d'), 'phase': r.phase,
                     'avg_power': float(r.avg_power or 0),
                     'peak_power': float(r.peak_power or 0),
                     'total_kwh': float(r.total_energy_kwh or 0)} for r in results]
        else:
            data = [{'date': r.date.strftime('%Y-%m'), 'phase': r.phase,
                     'avg_power': float(r.avg_power or 0),
                     'peak_power': float(r.peak_power or 0),
                     'total_kwh': float(r.total_kwh or 0)} for r in results]

        return {
            'data': data, 'total': total, 'page': page,
            'per_page': per_page, 'pages': max(1, (total + per_page - 1) // per_page)
        }

    # ── Aggregate data for report ─────────────────────────────────────────────

    def get_data_for_report(self, start_date, end_date, parameters='all'):
        if isinstance(start_date, str):
            start_date = datetime.fromisoformat(start_date).date()
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date).date()

        query = (
            self.session.query(
                DailyEnergyView.date,
                Sensor.phase,
                DailyEnergyView.avg_power,
                DailyEnergyView.peak_power,
                DailyEnergyView.total_energy_kwh,
                DailyEnergyView.avg_pf,
                DailyEnergyView.avg_voltage,
                DailyEnergyView.total_cost,
            )
            .join(Sensor, Sensor.id == DailyEnergyView.sensor_id)
            .filter(DailyEnergyView.date.between(start_date, end_date))
        )
        query = self._get_base_query_filter(query)
        query = query.order_by(DailyEnergyView.date.asc())
        return query.all()

    # ── CSV ───────────────────────────────────────────────────────────────────

    def generate_csv_report(self, data, start_date, end_date, building_name, parameters):
        output = io.StringIO()
        w = csv.writer(output)

        # Meta header
        w.writerow(['LAPORAN ENERGI LISTRIK'])
        w.writerow([f'Gedung/Departemen: {building_name}'])
        w.writerow([f'Periode: {start_date} s/d {end_date}'])
        w.writerow([f'Dibuat: {datetime.now().strftime("%d/%m/%Y %H:%M")}'])
        w.writerow([])

        # Column headers
        w.writerow(['Tanggal', 'Fasa', 'Avg Power (W)', 'Peak Power (W)',
                    'Total Energi (kWh)', 'Avg Tegangan (V)', 'Avg Power Factor',
                    'Estimasi Biaya (Rp)'])

        for r in data:
            w.writerow([
                r.date.strftime('%d/%m/%Y'), r.phase,
                f"{float(r.avg_power or 0):.2f}",
                f"{float(r.peak_power or 0):.2f}",
                f"{float(r.total_energy_kwh or 0):.4f}",
                f"{float(r.avg_voltage or 0):.1f}",
                f"{float(r.avg_pf or 0):.3f}",
                f"{float(r.total_cost or 0):.0f}",
            ])

        # Summary
        w.writerow([])
        w.writerow(['RINGKASAN'])
        total_kwh  = sum(float(r.total_energy_kwh or 0) for r in data)
        total_cost = sum(float(r.total_cost or 0) for r in data)
        peak       = max((float(r.peak_power or 0) for r in data), default=0)
        w.writerow(['Total Energi (kWh)', f'{total_kwh:.2f}'])
        w.writerow(['Peak Power (W)', f'{peak:.2f}'])
        w.writerow(['Total Estimasi Biaya', f'Rp {total_cost:,.0f}'])

        output.seek(0)
        filename = (f"laporan-energi-{building_name.replace(' ', '-')}"
                    f"-{start_date}-sd-{end_date}.csv")
        return send_file(
            io.BytesIO(output.getvalue().encode('utf-8-sig')),
            mimetype='text/csv', as_attachment=True, download_name=filename
        )

    # ── PDF ───────────────────────────────────────────────────────────────────

    def generate_pdf_report(self, data, start_date, end_date, building_name, parameters):
        buffer = io.BytesIO()
        PAGE   = A4
        doc    = SimpleDocTemplate(
            buffer, pagesize=PAGE,
            rightMargin=1.5*cm, leftMargin=1.5*cm,
            topMargin=2*cm, bottomMargin=2*cm,
            title=f"Laporan Energi - {building_name}",
            author="EnergyMon v2.0"
        )

        styles = getSampleStyleSheet()
        W      = PAGE[0] - 3*cm  # usable width

        # ── Custom styles ─────────────────────────────────────────────────────
        def sty(name, **kw):
            return ParagraphStyle(name, **kw)

        S = {
            'cover_title': sty('ct', fontSize=28, leading=34,
                               textColor=colors.white, fontName='Helvetica-Bold',
                               spaceAfter=4),
            'cover_sub':   sty('cs', fontSize=11, textColor=colors.HexColor('#bfdbfe'),
                               fontName='Helvetica', spaceAfter=2),
            'section':     sty('sec', fontSize=13, fontName='Helvetica-Bold',
                               textColor=C_PRIMARY, spaceBefore=14, spaceAfter=6,
                               borderPadding=(0,0,3,0)),
            'body':        sty('bd', fontSize=8.5, fontName='Helvetica',
                               textColor=C_DARK, leading=13),
            'label':       sty('lb', fontSize=7.5, fontName='Helvetica-Bold',
                               textColor=C_SLATE, spaceAfter=1),
            'kpi_val':     sty('kv', fontSize=20, fontName='Helvetica-Bold',
                               textColor=C_PRIMARY, leading=24),
            'kpi_sub':     sty('ks', fontSize=8, fontName='Helvetica',
                               textColor=C_SLATE),
            'caption':     sty('cap', fontSize=7.5, fontName='Helvetica',
                               textColor=C_SLATE, alignment=1, spaceAfter=4),
            'tbl_hdr':     sty('th', fontSize=8, fontName='Helvetica-Bold',
                               textColor=colors.white, alignment=1),
            'insight':     sty('ins', fontSize=8.5, fontName='Helvetica',
                               textColor=C_DARK, leading=13, leftIndent=10,
                               borderPadding=6, backColor=colors.HexColor('#eff6ff'),
                               borderColor=C_PRIMARY, borderWidth=0),
        }

        # ── Pre-process data ─────────────────────────────────────────────────
        # Group by date → {date: {R:row, S:row, T:row}}
        by_date = defaultdict(dict)
        for r in data:
            by_date[r.date][r.phase] = r

        dates_sorted = sorted(by_date.keys())

        def _agg(field):
            """Sum field across all phases per date."""
            result = {}
            for d, phases in by_date.items():
                result[d] = sum(float(getattr(v, field) or 0)
                                for v in phases.values())
            return result

        total_kwh_by_date  = _agg('total_energy_kwh')
        total_cost_by_date = _agg('total_cost')
        peak_by_date       = {
            d: max(float(v.peak_power or 0) for v in phases.values())
            for d, phases in by_date.items()
        }
        pf_by_date = {
            d: (sum(float(v.avg_pf or 0) for v in phases.values()) /
                max(len(phases), 1))
            for d, phases in by_date.items()
        }

        total_kwh   = sum(total_kwh_by_date.values())
        total_cost  = sum(total_cost_by_date.values())
        peak_power  = max(peak_by_date.values(), default=0)
        avg_pf      = (sum(pf_by_date.values()) / len(pf_by_date)
                       if pf_by_date else 0)
        n_days      = len(dates_sorted)
        avg_kwh_day = total_kwh / n_days if n_days else 0

        # Trend vs first-half vs second-half
        mid = n_days // 2
        first_half  = dates_sorted[:mid]
        second_half = dates_sorted[mid:]
        kwh_first   = sum(total_kwh_by_date[d] for d in first_half)
        kwh_second  = sum(total_kwh_by_date[d] for d in second_half)
        trend_pct   = _pct_change(kwh_second, kwh_first)

        # Per phase totals
        phase_totals = defaultdict(lambda: {'kwh': 0, 'cost': 0, 'peak': 0})
        for r in data:
            ph = r.phase
            phase_totals[ph]['kwh']  += float(r.total_energy_kwh or 0)
            phase_totals[ph]['cost'] += float(r.total_cost or 0)
            phase_totals[ph]['peak']  = max(phase_totals[ph]['peak'],
                                            float(r.peak_power or 0))

        story = []

        # ══════════════════════════════════════════════════════════════════════
        # HALAMAN 1 — COVER
        # ══════════════════════════════════════════════════════════════════════
        # Cover background via table with colored cell
        cover_data = [['']]
        cover_tbl  = Table(cover_data, colWidths=[W], rowHeights=[60])
        cover_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), C_HDR_BG),
            ('ROUNDEDCORNERS', [8]),
        ]))

        # Blue header bar
        header_tbl = Table(
            [[Paragraph('LAPORAN ENERGI LISTRIK', S['cover_title'])],
             [Paragraph('Energy Management Report', S['cover_sub'])]],
            colWidths=[W]
        )
        header_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), C_HDR_BG),
            ('TOPPADDING', (0,0), (-1,-1), 20),
            ('BOTTOMPADDING', (0,0), (-1,-1), 20),
            ('LEFTPADDING', (0,0), (-1,-1), 20),
            ('RIGHTPADDING', (0,0), (-1,-1), 20),
            ('ROUNDEDCORNERS', [8]),
        ]))
        story.append(header_tbl)
        story.append(Spacer(1, 12))

        # Meta info box
        meta_data = [
            ['Gedung / Departemen', ':', building_name],
            ['Periode Laporan',     ':', f"{start_date} s/d {end_date}"],
            ['Tanggal Dibuat',      ':', datetime.now().strftime('%d %B %Y, %H:%M WIB')],
            ['Durasi',             ':', f"{n_days} hari"],
        ]
        meta_tbl = Table(meta_data, colWidths=[4*cm, 0.5*cm, W-4.5*cm])
        meta_tbl.setStyle(TableStyle([
            ('FONTNAME',    (0,0), (-1,-1), 'Helvetica'),
            ('FONTSIZE',    (0,0), (-1,-1), 9),
            ('FONTNAME',    (0,0), (0,-1), 'Helvetica-Bold'),
            ('TEXTCOLOR',   (0,0), (0,-1), C_DARK),
            ('TEXTCOLOR',   (2,0), (2,-1), C_SLATE),
            ('TOPPADDING',  (0,0), (-1,-1), 3),
            ('BOTTOMPADDING',(0,0),(-1,-1), 3),
            ('BACKGROUND',  (0,0), (-1,-1), C_LIGHT),
            ('BOX',         (0,0), (-1,-1), 0.5, C_BORDER),
            ('INNERGRID',   (0,0), (-1,-1), 0.3, C_BORDER),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING',(0,0), (-1,-1), 10),
        ]))
        story.append(meta_tbl)
        story.append(Spacer(1, 20))

        # ── KPI Cards (4 kotak besar) ─────────────────────────────────────
        trend_txt, trend_col = _trend_arrow(trend_pct)
        kpi_items = [
            ('Total Energi', f"{total_kwh:,.2f}", 'kWh', None, None),
            ('Estimasi Biaya', f"Rp {total_cost/1_000_000:,.2f}", 'Juta Rupiah', None, None),
            ('Peak Power', f"{peak_power/1000:,.2f}", 'kW', None, None),
            ('Avg Power Factor', f"{avg_pf:.3f}", 'rata-rata', None, None),
        ]

        kpi_cells = []
        for label, val, unit, _, __ in kpi_items:
            cell = [
                Paragraph(label, S['label']),
                Paragraph(val, S['kpi_val']),
                Paragraph(unit, S['kpi_sub']),
            ]
            kpi_cells.append(cell)

        kpi_tbl = Table([kpi_cells], colWidths=[W/4]*4)
        kpi_tbl.setStyle(TableStyle([
            ('BACKGROUND',  (0,0), (-1,-1), colors.white),
            ('BOX',         (0,0), (-1,-1), 0.5, C_BORDER),
            ('INNERGRID',   (0,0), (-1,-1), 0.5, C_BORDER),
            ('TOPPADDING',  (0,0), (-1,-1), 10),
            ('BOTTOMPADDING',(0,0),(-1,-1), 10),
            ('LEFTPADDING', (0,0), (-1,-1), 12),
            ('VALIGN',      (0,0), (-1,-1), 'TOP'),
        ]))
        story.append(Paragraph('Ringkasan Eksekutif', S['section']))
        story.append(kpi_tbl)
        story.append(Spacer(1, 10))

        # Trend insight
        # trend_sentence = (
        #     f"Tren konsumsi energi {'meningkat' if (trend_pct or 0) > 0 else 'menurun'} "
        #     f"{abs(trend_pct or 0):.1f}% pada paruh kedua periode dibanding paruh pertama. "
        #     f"Rata-rata konsumsi harian: {avg_kwh_day:,.2f} kWh/hari."
        # )
        # story.append(Paragraph(f"📊  {trend_sentence}", S['insight']))
        # story.append(Spacer(1, 6))

        pf_insight = (
            'Baik (≥0.90)' if avg_pf >= 0.90
            else 'Perlu Perbaikan (<0.90)'
        )
        story.append(Paragraph(
            f"⚡  Power factor rata-rata {avg_pf:.3f} — {pf_insight}. "
            f"Power factor rendah meningkatkan biaya daya reaktif.",
            S['insight']
        ))
        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # HALAMAN 2 — TREN ENERGI HARIAN
        # ══════════════════════════════════════════════════════════════════════
        story.append(Paragraph('Tren Konsumsi Energi Harian', S['section']))
        story.append(HRFlowable(width=W, thickness=0.5, color=C_BORDER, spaceAfter=6))

        # Sparkline chart
        kwh_r = [float(by_date[d].get('R', None) and
                       by_date[d]['R'].total_energy_kwh or 0) for d in dates_sorted]
        kwh_s = [float(by_date[d].get('S', None) and
                       by_date[d]['S'].total_energy_kwh or 0) for d in dates_sorted]
        kwh_t = [float(by_date[d].get('T', None) and
                       by_date[d]['T'].total_energy_kwh or 0) for d in dates_sorted]

        spark = _mini_line_chart(kwh_r, kwh_s, kwh_t, w=W-20, h=80)
        spark.hAlign = 'CENTER'
        story.append(spark)

        # Legend
        legend = Table(
            [['', 'Fasa R', '', 'Fasa S', '', 'Fasa T']],
            colWidths=[1*cm, 2*cm, 1*cm, 2*cm, 1*cm, 2*cm]
        )
        legend.setStyle(TableStyle([
            ('FONTNAME',  (0,0),(-1,-1),'Helvetica'), ('FONTSIZE',(0,0),(-1,-1),8),
            ('TEXTCOLOR', (1,0),(1,0), C_PHASE_R),
            ('TEXTCOLOR', (3,0),(3,0), C_PHASE_S),
            ('TEXTCOLOR', (5,0),(5,0), C_PHASE_T),
            ('FONTNAME',  (1,0),(1,0),'Helvetica-Bold'),
            ('FONTNAME',  (3,0),(3,0),'Helvetica-Bold'),
            ('FONTNAME',  (5,0),(5,0),'Helvetica-Bold'),
            ('TOPPADDING',(0,0),(-1,-1),0),
        ]))
        story.append(legend)
        story.append(Spacer(1, 10))

        # Daily table (max 31 baris)
        tbl_hdr = [
            [Paragraph('Tanggal', S['tbl_hdr']),
             Paragraph('Total kWh', S['tbl_hdr']),
             Paragraph('Peak Power (kW)', S['tbl_hdr']),
             Paragraph('Avg PF', S['tbl_hdr']),
             Paragraph('Est. Biaya (Rp)', S['tbl_hdr']),
             Paragraph('Trend', S['tbl_hdr'])],
        ]
        prev_kwh = None
        tbl_rows = []
        for i, d in enumerate(dates_sorted):
            kwh  = total_kwh_by_date[d]
            pk   = peak_by_date[d] / 1000
            pf   = pf_by_date[d]
            cost = total_cost_by_date[d]
            chg  = _pct_change(kwh, prev_kwh) if prev_kwh is not None else None
            arr, col = _trend_arrow(chg)
            tbl_rows.append([
                d.strftime('%d %b %Y'),
                _fmt_num(kwh, 3),
                _fmt_num(pk, 2),
                _fmt_num(pf, 3),
                f"Rp {cost:,.0f}",
                arr,
            ])
            prev_kwh = kwh

        daily_tbl = Table(
            tbl_hdr + tbl_rows,
            colWidths=[2.8*cm, 2.3*cm, 2.8*cm, 2*cm, 3.5*cm, 2*cm],
            repeatRows=1
        )
        style_cmds = [
            ('BACKGROUND',   (0,0), (-1,0),  C_HDR_BG),
            ('TEXTCOLOR',    (0,0), (-1,0),  colors.white),
            ('FONTNAME',     (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',     (0,0), (-1,-1), 8),
            ('FONTNAME',     (0,1), (-1,-1), 'Helvetica'),
            ('TEXTCOLOR',    (0,1), (-1,-1), C_DARK),
            ('ALIGN',        (1,0), (-1,-1), 'RIGHT'),
            ('ALIGN',        (0,0), (0,-1),  'LEFT'),
            ('GRID',         (0,0), (-1,-1), 0.3, C_BORDER),
            ('TOPPADDING',   (0,0), (-1,-1), 4),
            ('BOTTOMPADDING',(0,0), (-1,-1), 4),
            ('LEFTPADDING',  (0,0), (-1,-1), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ]
        for i in range(1, len(tbl_rows) + 1):
            bg = C_ROW_ODD if i % 2 == 1 else C_ROW_EVEN
            style_cmds.append(('BACKGROUND', (0,i), (-1,i), bg))

        # Color trend cells
        for i, d in enumerate(dates_sorted):
            kwh  = total_kwh_by_date[d]
            prev = total_kwh_by_date.get(dates_sorted[i-1]) if i > 0 else None
            chg  = _pct_change(kwh, prev) if prev else None
            col  = C_DANGER if (chg or 0) > 0 else C_SUCCESS if (chg or 0) < 0 else C_SLATE
            style_cmds.append(('TEXTCOLOR', (5, i+1), (5, i+1), col))

        daily_tbl.setStyle(TableStyle(style_cmds))
        story.append(daily_tbl)
        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # HALAMAN 3 — ANALISIS PER FASA
        # ══════════════════════════════════════════════════════════════════════
        story.append(Paragraph('Analisis per Fasa', S['section']))
        story.append(HRFlowable(width=W, thickness=0.5, color=C_BORDER, spaceAfter=6))

        # Phase summary cards
        PHASE_HEX = {'R': 'ef4444', 'S': 'eab308', 'T': '3b82f6'}
        ph_cells = []
        for ph, col in [('R', C_PHASE_R), ('S', C_PHASE_S), ('T', C_PHASE_T)]:
            pt = phase_totals.get(ph, {})
            ph_cells.append([
                Paragraph(f'<font color="#{PHASE_HEX[ph]}">● </font>'
                          f'<b>Fasa {ph}</b>', S['body']),
                Paragraph(f"{_fmt_num(pt.get('kwh',0), 3)} kWh", S['kpi_val']),
                Paragraph(f"Peak: {pt.get('peak',0)/1000:.2f} kW", S['kpi_sub']),
                Paragraph(f"Biaya: Rp {pt.get('cost',0):,.0f}", S['kpi_sub']),
            ])

        ph_tbl = Table([ph_cells], colWidths=[W/3]*3)
        ph_tbl.setStyle(TableStyle([
            ('BOX',          (0,0),(-1,-1), 0.5, C_BORDER),
            ('INNERGRID',    (0,0),(-1,-1), 0.5, C_BORDER),
            ('BACKGROUND',   (0,0),(-1,-1), colors.white),
            ('TOPPADDING',   (0,0),(-1,-1), 10),
            ('BOTTOMPADDING',(0,0),(-1,-1), 10),
            ('LEFTPADDING',  (0,0),(-1,-1), 12),
            ('VALIGN',       (0,0),(-1,-1), 'TOP'),
        ]))
        story.append(ph_tbl)
        story.append(Spacer(1, 12))

        # Per-phase daily detail table
        story.append(Paragraph('Detail Harian per Fasa', S['label']))
        story.append(Spacer(1, 4))

        ph_hdr = [[
            Paragraph('Tanggal',    S['tbl_hdr']),
            Paragraph('R kWh',      S['tbl_hdr']),
            Paragraph('R Peak kW',  S['tbl_hdr']),
            Paragraph('R PF',       S['tbl_hdr']),
            Paragraph('S kWh',      S['tbl_hdr']),
            Paragraph('S Peak kW',  S['tbl_hdr']),
            Paragraph('S PF',       S['tbl_hdr']),
            Paragraph('T kWh',      S['tbl_hdr']),
            Paragraph('T Peak kW',  S['tbl_hdr']),
            Paragraph('T PF',       S['tbl_hdr']),
        ]]
        ph_rows = []
        for d in dates_sorted:
            phases = by_date[d]
            row = [d.strftime('%d/%m')]
            for ph in ('R', 'S', 'T'):
                r = phases.get(ph)
                row += [
                    _fmt_num(float(r.total_energy_kwh or 0) if r else None, 3),
                    _fmt_num(float(r.peak_power or 0)/1000 if r else None, 2),
                    _fmt_num(float(r.avg_pf or 0) if r else None, 3),
                ]
            ph_rows.append(row)

        ph_detail_tbl = Table(
            ph_hdr + ph_rows,
            colWidths=[1.5*cm] + [1.7*cm]*9,
            repeatRows=1
        )
        ph_style = [
            ('BACKGROUND',   (0,0), (-1,0),  C_HDR_BG),
            ('TEXTCOLOR',    (0,0), (-1,0),  colors.white),
            ('FONTNAME',     (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',     (0,0), (-1,-1), 7),
            ('FONTNAME',     (0,1), (-1,-1), 'Helvetica'),
            ('TEXTCOLOR',    (0,1), (-1,-1), C_DARK),
            ('ALIGN',        (1,0), (-1,-1), 'RIGHT'),
            ('ALIGN',        (0,0), (0,-1),  'LEFT'),
            ('GRID',         (0,0), (-1,-1), 0.3, C_BORDER),
            ('TOPPADDING',   (0,0), (-1,-1), 3),
            ('BOTTOMPADDING',(0,0), (-1,-1), 3),
            ('LEFTPADDING',  (0,0), (-1,-1), 4),
            ('RIGHTPADDING', (0,0), (-1,-1), 4),
            # Column group color hint
            ('TEXTCOLOR',    (1,0), (3,0),   C_PHASE_R),
            ('TEXTCOLOR',    (4,0), (6,0),   C_PHASE_S),
            ('TEXTCOLOR',    (7,0), (9,0),   C_PHASE_T),
        ]
        for i in range(1, len(ph_rows)+1):
            ph_style.append(('BACKGROUND', (0,i), (-1,i),
                              C_ROW_ODD if i%2==1 else C_ROW_EVEN))
        ph_detail_tbl.setStyle(TableStyle(ph_style))
        story.append(ph_detail_tbl)
        story.append(PageBreak())

        # ══════════════════════════════════════════════════════════════════════
        # HALAMAN 4 — RINGKASAN & REKOMENDASI
        # ══════════════════════════════════════════════════════════════════════
        story.append(Paragraph('Ringkasan', S['section']))
        story.append(HRFlowable(width=W, thickness=0.5, color=C_BORDER, spaceAfter=8))

        # Summary table
        sum_data = [
            ['Parameter',                  'Nilai',                     'Keterangan'],
            ['Total Konsumsi Energi',
             f"{total_kwh:,.3f} kWh",
             f"Rata-rata {avg_kwh_day:.2f} kWh/hari"],
            ['Total Estimasi Biaya',
             f"Rp {total_cost:,.0f}",
             f"Rata-rata Rp {total_cost/n_days:,.0f}/hari" if n_days else '—'],
            ['Peak Power Tertinggi',
             f"{peak_power/1000:.2f} kW",
             'Perhatikan beban puncak'],
            ['Avg Power Factor',
             f"{avg_pf:.3f}",
             'Baik (≥0.90)' if avg_pf >= 0.90 else 'Perlu perbaikan'],
            # ['Tren Konsumsi',
            #  f"{trend_txt}",
            #  'vs paruh pertama periode'],
        ]
        sum_tbl = Table(sum_data, colWidths=[4.5*cm, 4*cm, W-8.5*cm], repeatRows=1)
        sum_style = [
            ('BACKGROUND',   (0,0), (-1,0),  C_HDR_BG),
            ('TEXTCOLOR',    (0,0), (-1,0),  colors.white),
            ('FONTNAME',     (0,0), (-1,0),  'Helvetica-Bold'),
            ('FONTSIZE',     (0,0), (-1,-1), 8.5),
            ('FONTNAME',     (0,1), (-1,-1), 'Helvetica'),
            ('FONTNAME',     (0,1), (0,-1),  'Helvetica-Bold'),
            ('TEXTCOLOR',    (0,1), (0,-1),  C_DARK),
            ('TEXTCOLOR',    (1,1), (1,-1),  C_PRIMARY),
            ('GRID',         (0,0), (-1,-1), 0.3, C_BORDER),
            ('TOPPADDING',   (0,0), (-1,-1), 6),
            ('BOTTOMPADDING',(0,0), (-1,-1), 6),
            ('LEFTPADDING',  (0,0), (-1,-1), 8),
        ]
        for i in range(1, len(sum_data)):
            sum_style.append(('BACKGROUND', (0,i), (-1,i),
                               C_ROW_ODD if i%2==1 else C_ROW_EVEN))
        # Color tren row
        sum_style.append(('TEXTCOLOR', (1, 5), (1, 5), trend_col))
        sum_tbl.setStyle(TableStyle(sum_style))
        story.append(sum_tbl)
        story.append(Spacer(1, 16))

        # Rekomendasi
        # story.append(Paragraph('Rekomendasi Manajemen Energi', S['section']))
        # story.append(HRFlowable(width=W, thickness=0.5, color=C_BORDER, spaceAfter=8))

        # recommendations = []
        # if avg_pf < 0.90:
        #     recommendations.append(
        #         '⚠️  Power factor di bawah 0.90. Pertimbangkan pemasangan kapasitor bank '
        #         'untuk meningkatkan power factor dan mengurangi biaya daya reaktif.'
        #     )
        # if trend_pct and trend_pct > 5:
        #     recommendations.append(
        #         f'📈  Konsumsi energi meningkat {trend_pct:.1f}% pada paruh kedua periode. '
        #         'Lakukan audit penggunaan peralatan listrik dan jadwalkan pemeliharaan rutin.'
        #     )
        # if trend_pct and trend_pct < -5:
        #     recommendations.append(
        #         f'✅  Konsumsi energi menurun {abs(trend_pct):.1f}% — program efisiensi berjalan baik. '
        #         'Pertahankan praktik ini dan dokumentasikan best practice.'
        #     )

        # Phase imbalance check
        # ph_kwh_vals = [phase_totals[ph]['kwh'] for ph in ('R','S','T')
        #                if ph in phase_totals]
        # if ph_kwh_vals:
        #     ph_max = max(ph_kwh_vals)
        #     ph_min = min(ph_kwh_vals)
        #     if ph_max > 0 and (ph_max - ph_min) / ph_max > 0.10:
        #         recommendations.append(
        #             '⚖️  Ketidakseimbangan beban antar fasa >10%. '
        #             'Distribusikan ulang beban antara fasa R, S, T untuk efisiensi optimal.'
        #         )

        # if not recommendations:
        #     recommendations.append(
        #         '✅  Sistem berjalan dalam kondisi normal. '
        #         'Lanjutkan monitoring rutin dan pertahankan efisiensi operasional.'
        #     )

        # for rec in recommendations:
        #     rec_tbl = Table([[Paragraph(rec, S['body'])]], colWidths=[W])
        #     rec_tbl.setStyle(TableStyle([
        #         ('BACKGROUND',   (0,0),(-1,-1), colors.HexColor('#eff6ff')),
        #         ('BOX',          (0,0),(-1,-1), 0.5, C_PRIMARY),
        #         ('LEFTPADDING',  (0,0),(-1,-1), 10),
        #         ('RIGHTPADDING', (0,0),(-1,-1), 10),
        #         ('TOPPADDING',   (0,0),(-1,-1), 8),
        #         ('BOTTOMPADDING',(0,0),(-1,-1), 8),
        #     ]))
        #     story.append(rec_tbl)
        #     story.append(Spacer(1, 6))

        # Footer note
        story.append(Spacer(1, 20))
        story.append(HRFlowable(width=W, thickness=0.3, color=C_BORDER))
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            f'Laporan ini dibuat secara otomatis pada '
            f'{datetime.now().strftime("%d %B %Y pukul %H:%M WIB")}. '
            f'Data bersumber dari sistem monitoring energi real-time.',
            S['caption']
        ))

        # ── Build ─────────────────────────────────────────────────────────────
        def _header_footer(canvas, doc):
            canvas.saveState()
            # Header bar
            canvas.setFillColor(C_HDR_BG)
            canvas.rect(1.5*cm, A4[1]-1.4*cm, W, 0.6*cm, fill=1, stroke=0)
            canvas.setFillColor(colors.white)
            canvas.setFont('Helvetica-Bold', 7)
            canvas.drawString(1.8*cm, A4[1]-1.1*cm, 'LAPORAN ENERGI LISTRIK')
            canvas.setFont('Helvetica', 7)
            canvas.drawRightString(A4[0]-1.5*cm, A4[1]-1.1*cm,
                                   f'{building_name}  |  {start_date} s/d {end_date}')
            # Footer
            canvas.setFillColor(C_SLATE)
            canvas.setFont('Helvetica', 7)
            canvas.drawString(1.5*cm, 1.4*cm, 'EnergyMon v2.0 — Confidential')
            canvas.drawRightString(A4[0]-1.5*cm, 1.4*cm,
                                   f'Halaman {doc.page}')
            canvas.restoreState()

        doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
        buffer.seek(0)

        filename = (f"laporan-energi-{building_name.replace(' ','-')}"
                    f"-{start_date}-sd-{end_date}.pdf")
        return send_file(
            buffer, mimetype='application/pdf',
            as_attachment=True, download_name=filename
        )