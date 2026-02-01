from flask import Blueprint, render_template, jsonify, request, send_file
from controllers.reports_controller import ReportsController
from database import get_session
import csv
import io

reports_bp = Blueprint('reports', __name__)

@reports_bp.route('/')
def index():
    return render_template('reports.html')


@reports_bp.route('/history')
def get_history():
    session = get_session()
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        period = request.args.get('period', 'hourly', type=str)

        if period not in ['hourly', 'daily', 'monthly']:
            return jsonify({'error': 'Invalid period'}), 400

        controller = ReportsController(session)
        data = controller.get_history(page, per_page, period)

        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@reports_bp.route('/generate-report', methods=['POST'])
def generate_report():
    session = get_session()
    try:
        payload = request.get_json()

        start_date = payload.get('start_date')
        end_date = payload.get('end_date')
        period = payload.get('period', 'daily')
        format_type = payload.get('format', 'csv')

        if period not in ['daily', 'monthly']:
            return jsonify({'error': 'Report only supports daily or monthly'}), 400

        controller = ReportsController(session)

        report = controller.get_history(
            page=1,
            per_page=10_000,
            period=period
        )

        if not report['data']:
            return jsonify({'error': 'No data available'}), 404

        if format_type == 'csv':
            return generate_csv_report(
                report['data'],
                start_date,
                end_date,
                period
            )

        return jsonify({'error': 'Invalid format'}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


def generate_csv_report(data, start_date, end_date, period):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)

    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'energy-report-{period}-{start_date}-to-{end_date}.csv'
    )