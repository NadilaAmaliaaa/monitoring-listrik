# controllers/reports_controller.py
from datetime import datetime, timedelta
from sqlalchemy import func, text
from models.views import HourlyEnergyView, DailyEnergyView
from models.data import Sensor
from models.building import Building
import csv
import io
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import Table
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.pdfgen import canvas
from flask import send_file


class ReportsController:
    def __init__(self, session, building_id=None):
        self.session = session
        self.building_id = building_id
    
    def _get_base_query_filter(self, query):
        """Apply building filter to query"""
        if self.building_id:
            query = query.filter(Sensor.building_id == self.building_id)
        return query
    
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
                    Sensor.building_id,
                    HourlyEnergyView.avg_power,
                    HourlyEnergyView.peak_power,
                    HourlyEnergyView.total_kwh
                )
                .join(Sensor, Sensor.id == HourlyEnergyView.sensor_id)
                .filter(HourlyEnergyView.date >= start_date)
                .filter(HourlyEnergyView.date < end_date)
            )
            
            # Apply building filter
            query = self._get_base_query_filter(query)
            query = query.order_by(HourlyEnergyView.date.desc())

        elif period == 'daily':
            start_date = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            end_date = now

            query = (
                self.session.query(
                    DailyEnergyView.date,
                    Sensor.phase,
                    Sensor.building_id,
                    DailyEnergyView.avg_power,
                    DailyEnergyView.peak_power,
                    DailyEnergyView.total_energy_kwh
                )
                .join(Sensor, Sensor.id == DailyEnergyView.sensor_id)
                .filter(DailyEnergyView.date >= start_date)
                .filter(DailyEnergyView.date <= end_date)
            )
            
            query = self._get_base_query_filter(query)
            query = query.order_by(DailyEnergyView.date.desc())

        elif period == 'monthly':
            start_date = now.replace(
                month=1, day=1, hour=0, minute=0, second=0, microsecond=0
            )
            end_date = now

            query = (
                self.session.query(
                    func.date_trunc('month', DailyEnergyView.date).label('date'),
                    Sensor.phase,
                    Sensor.building_id,
                    func.avg(DailyEnergyView.avg_power).label('avg_power'),
                    func.max(DailyEnergyView.peak_power).label('peak_power'),
                    func.sum(DailyEnergyView.total_energy_kwh).label('total_kwh')
                )
                .join(Sensor, Sensor.id == DailyEnergyView.sensor_id)
                .filter(DailyEnergyView.date >= start_date)
                .filter(DailyEnergyView.date <= end_date)
            )
            
            query = self._get_base_query_filter(query)
            query = query.group_by(
                func.date_trunc('month', DailyEnergyView.date),
                Sensor.phase,
                Sensor.building_id
            ).order_by(text('date DESC'))

        total = query.count()
        results = query.offset(offset).limit(per_page).all()

        # Serialization
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

    def get_data_for_report(self, start_date, end_date, parameters='all'):
        # Parse dates
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
                DailyEnergyView.total_energy_kwh
            )
            .join(Sensor, Sensor.id == DailyEnergyView.sensor_id)
            .filter(
                DailyEnergyView.date.between(start_date, end_date)
            )
        )

        # =============================
        # Filter berdasarkan building terpilih
        # (misal: Sensor.building_id == active_building_id)
        # =============================
        query = self._get_base_query_filter(query)

        # =============================
        # Ordering
        # =============================
        query = query.order_by(DailyEnergyView.date.asc())

        results = query.all()

        # =============================
        # Serialization
        # =============================
        data = []
        for row in results:
            record = {
                "date": row.date.isoformat(),  # YYYY-MM-DD
                "phase": row.phase
            }

            if parameters in ["all", "power"]:
                record["avg_power"] = float(row.avg_power or 0)
                record["peak_power"] = float(row.peak_power or 0)

            if parameters in ["all", "energy"]:
                record["total_kwh"] = float(row.total_energy_kwh or 0)

            data.append(record)

        return data
    
    def generate_csv_report(self, data, start_date, end_date, building_name, parameters):
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        headers = ["Date", "Phase"]

        if parameters in ["all", "power"]:
            headers += ["Avg Power", "Peak Power"]

        if parameters in ["all", "energy"]:
            headers += ["Total kWh"]

        writer.writerow(headers)

        # Rows
        for row in data:
            record = [row["date"], row["phase"]]

            if parameters in ["all", "power"]:
                record += [
                    row.get("avg_power", 0),
                    row.get("peak_power", 0)
                ]

            if parameters in ["all", "energy"]:
                record.append(row.get("total_kwh", 0))

            writer.writerow(record)

        output.seek(0)

        filename = (
            f"energy-report-"
            f"{building_name.replace(' ', '-')}-"
            f"{start_date}-to-{end_date}.csv"
        )

        return send_file(
            io.BytesIO(output.getvalue().encode("utf-8")),
            mimetype="text/csv",
            as_attachment=True,
            download_name=filename
        )

    def generate_pdf_report(self, data, start_date, end_date, building_name, parameters):
        buffer = io.BytesIO()

        # ─────────────────────────────
        # Determine columns
        # ─────────────────────────────
        headers = ["Date", "Phase"]

        if parameters in ["all", "power"]:
            headers += ["Avg Power (Watt)", "Peak Power (Watt)"]

        if parameters in ["all", "energy"]:
            headers += ["Total Energy (kWh)"]

        column_count = len(headers)

        # Auto landscape kalau kolom banyak
        pagesize = landscape(A4) if column_count > 4 else A4

        doc = SimpleDocTemplate(
            buffer,
            pagesize=pagesize,
            rightMargin=30,
            leftMargin=30,
            topMargin=40,
            bottomMargin=30
        )

        elements = []

        styles = getSampleStyleSheet()

        # =============================
        # Title Style Center
        # =============================
        center_title = ParagraphStyle(
            'CenterTitle',
            parent=styles['Heading1'],
            alignment=1,  # CENTER
            spaceAfter=10
        )

        center_normal = ParagraphStyle(
            'CenterNormal',
            parent=styles['Normal'],
            alignment=1,
            spaceAfter=20
        )

        elements.append(Paragraph(f"Energy Report - {building_name}", center_title))
        elements.append(Paragraph(f"Period: {start_date} to {end_date}", center_normal))
        elements.append(Spacer(1, 0.2 * inch))

        # =============================
        # Table Data
        # =============================
        table_data = [headers]

        for row in data:
            record = [
                str(row.get("date", "")),
                str(row.get("phase", ""))
            ]

            if parameters in ["all", "power"]:
                record += [
                    f"{float(row.get('avg_power') or 0):.2f}",
                    f"{float(row.get('peak_power') or 0):.2f}"
                ]

            if parameters in ["all", "energy"]:
                record.append(f"{float(row.get('total_kwh') or 0):.2f}")

            table_data.append(record)

        # =============================
        # Full Width Table
        # =============================
        page_width = pagesize[0] - doc.leftMargin - doc.rightMargin
        col_width = page_width / column_count
        col_widths = [col_width] * column_count

        table = Table(table_data, colWidths=col_widths, repeatRows=1)

        table.setStyle(TableStyle([
            # Header background
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),

            # Grid lines
            ("GRID", (0, 0), (-1, -1), 0.75, colors.black),

            # Font
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),

            # Alignment
            ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

            # Padding
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))

        elements.append(table)

        doc.build(elements)
        buffer.seek(0)

        filename = (
            f"energy-report-"
            f"{building_name.replace(' ', '-')}-"
            f"{start_date}-to-{end_date}.pdf"
        )

        return send_file(
            buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )