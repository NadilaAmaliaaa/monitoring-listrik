from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/analytics')
def analytics():
    return render_template('analytics.html')

@app.route('/reports')
def reports():
    return render_template('reports.html')

@app.route('/alarms')
def alarms():
    return render_template('alarms.html')

@app.route('/settings')
def settings():
    return render_template('settings.html')

@app.route('/view')
def view():
    return render_template('viewmode.html')

if __name__ == '__main__':
    app.run(debug=True)