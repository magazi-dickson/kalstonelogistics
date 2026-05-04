from flask import Flask, render_template, request, flash, redirect, url_for, jsonify, session
import sqlite3
import os
import uuid
import hmac
import hashlib
import subprocess
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = 'kalstone_secret_key_cargo_2026_XkQ9!'

# GitHub webhook secret — must match what you set in GitHub
WEBHOOK_SECRET = 'kalstone_deploy_2026!'

# ─── Database Setup ──────────────────────────────────────────────────────────

DB_PATH = os.path.join(os.path.dirname(__file__), 'cargo.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create tables and seed demo data if DB doesn't exist."""
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS shipments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_id TEXT    UNIQUE NOT NULL,
            shipper_name TEXT   NOT NULL,
            consignee_name TEXT NOT NULL,
            origin      TEXT    NOT NULL,
            destination TEXT    NOT NULL,
            description TEXT    NOT NULL,
            weight      REAL    DEFAULT 0,
            volume      REAL    DEFAULT 0,
            status      TEXT    DEFAULT 'Booking Confirmed',
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL,
            est_delivery TEXT,
            mode        TEXT    DEFAULT 'Sea Freight'
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS tracking_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            shipment_id  INTEGER NOT NULL,
            event_status TEXT    NOT NULL,
            location     TEXT    NOT NULL,
            notes        TEXT,
            timestamp    TEXT    NOT NULL,
            FOREIGN KEY (shipment_id) REFERENCES shipments(id)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS admin_users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    # Seed admin user (default: admin / kalstone2026)
    c.execute("SELECT COUNT(*) FROM admin_users")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO admin_users (username, password) VALUES (?,?)", ('admin', 'kalstone2026'))

    # Seed demo shipments
    c.execute("SELECT COUNT(*) FROM shipments")
    if c.fetchone()[0] == 0:
        _seed_demo_data(c)

    conn.commit()
    conn.close()

def _seed_demo_data(c):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    shipments = [
        ('KL-2026-001', 'ABC Imports Ltd', 'XYZ Exports Co.', 'Shanghai, China', 'Dar es Salaam, Tanzania',
         'Electronics & Machinery Parts', 2450.5, 14.2, 'In Transit', now, now, '2026-05-20', 'Sea Freight'),
        ('KL-2026-002', 'Green Foods Ltd', 'Healthy Market TZ', 'Mombasa, Kenya', 'Dodoma, Tanzania',
         'Food Grade Products - Perishable', 800.0, 4.5, 'Customs Clearance', now, now, '2026-05-10', 'Road Freight'),
        ('KL-2026-003', 'Tech Hub Inc', 'Digital Africa Ltd', 'Dubai, UAE', 'Dar es Salaam, Tanzania',
         'IT Equipment & Accessories', 320.0, 2.1, 'Delivered', now, now, '2026-05-02', 'Air Freight'),
    ]
    c.executemany(
        "INSERT INTO shipments (tracking_id,shipper_name,consignee_name,origin,destination,description,weight,volume,status,created_at,updated_at,est_delivery,mode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        shipments
    )
    # Events for KL-2026-001
    events_001 = [
        (1, 'Booking Confirmed',  'Kalstone Office, Dar es Salaam', 'Booking received and confirmed.', '2026-04-25 09:00:00'),
        (1, 'Cargo Received',     'Shanghai Port, China',           'Cargo received at origin warehouse.', '2026-04-28 14:30:00'),
        (1, 'Vessel Departed',    'Shanghai Port, China',           'Vessel MSC AURORA departed port.', '2026-05-01 06:00:00'),
        (1, 'In Transit',         'Indian Ocean',                   'Shipment en route to Dar es Salaam.', '2026-05-03 12:00:00'),
    ]
    # Events for KL-2026-002
    events_002 = [
        (2, 'Booking Confirmed',  'Kalstone Office, Dar es Salaam', 'Booking received and confirmed.', '2026-05-01 10:00:00'),
        (2, 'Cargo Received',     'Mombasa Port, Kenya',            'Cargo loaded at origin.', '2026-05-03 08:00:00'),
        (2, 'Border Clearance',   'Namanga Border, Kenya/Tanzania', 'Cargo cleared at Namanga.', '2026-05-05 15:00:00'),
        (2, 'Customs Clearance',  'TRA Customs, Dodoma',            'Awaiting TRA customs inspection.', '2026-05-06 09:00:00'),
    ]
    # Events for KL-2026-003
    events_003 = [
        (3, 'Booking Confirmed',  'Kalstone Office, Dar es Salaam', 'Booking received.', '2026-04-20 08:00:00'),
        (3, 'Cargo Received',     'Dubai Airport, UAE',             'Cargo checked in at origin airport.', '2026-04-22 12:00:00'),
        (3, 'Flight Departed',    'Dubai International Airport',    'Flight EK 723 departed.', '2026-04-23 01:00:00'),
        (3, 'Arrived at Hub',     'JNIA Airport, Dar es Salaam',    'Cargo arrived at destination airport.', '2026-04-23 11:00:00'),
        (3, 'Customs Cleared',    'Tanzania Revenue Authority',     'All duties paid and cleared.', '2026-04-24 14:00:00'),
        (3, 'Out for Delivery',   'Kalstone Warehouse, Dar es Salaam', 'Driver en route to consignee.', '2026-05-01 09:00:00'),
        (3, 'Delivered',          'Digital Africa Office, Dar es Salaam', 'Shipment delivered. Signed by: J. Moyo', '2026-05-02 11:30:00'),
    ]
    c.executemany(
        "INSERT INTO tracking_events (shipment_id,event_status,location,notes,timestamp) VALUES (?,?,?,?,?)",
        events_001 + events_002 + events_003
    )

# Init DB on startup
init_db()

# ─── Admin Auth ───────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('Please log in to access the admin panel.', 'warning')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

STATUS_LIST = [
    'Booking Confirmed', 'Cargo Received', 'Vessel Departed', 'Flight Departed',
    'In Transit', 'Arrived at Hub', 'Border Clearance', 'Customs Clearance',
    'Customs Cleared', 'Out for Delivery', 'Delivered', 'On Hold', 'Cancelled'
]

TRANSPORT_MODES = ['Sea Freight', 'Air Freight', 'Road Freight', 'Rail Freight', 'Multimodal']

# ─── Public Routes ────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html', title='Home')

@app.route('/about')
def about():
    return render_template('about.html', title='About Us')

@app.route('/services')
def services():
    return render_template('services.html', title='Our Services')

@app.route('/blog')
def blog():
    posts = [
        {
            'title': 'Navigating Customs Clearance in Tanzania',
            'date': 'May 1, 2026',
            'excerpt': 'A comprehensive guide on how to smoothly clear your goods through Tanzanian customs without unnecessary delays.',
            'image': 'https://images.unsplash.com/photo-1578575437130-527eed3abbec?auto=format&fit=crop&w=800&q=80'
        },
        {
            'title': 'Top 5 Trends in Global Freight Forwarding',
            'date': 'April 15, 2026',
            'excerpt': 'Explore the latest innovations and trends shaping the future of global freight and logistics.',
            'image': 'https://images.unsplash.com/photo-1494412574643-ff11b0a5c1c3?auto=format&fit=crop&w=800&q=80'
        },
        {
            'title': 'Why Choose Trans-shipment?',
            'date': 'March 28, 2026',
            'excerpt': 'Understanding the benefits of trans-shipment operations for minimizing handling delays and maximizing efficiency.',
            'image': 'https://images.unsplash.com/photo-1578575437130-527eed3abbec?auto=format&fit=crop&w=800&q=80'
        }
    ]
    return render_template('blog.html', title='Blog & News', posts=posts)

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        flash(f'Thank you, {name}! Your message has been received. We will get back to you shortly.', 'success')
        return redirect(url_for('contact'))
    return render_template('contact.html', title='Contact Us')

# ─── Public Tracking ──────────────────────────────────────────────────────────

@app.route('/track', methods=['GET', 'POST'])
def track():
    shipment = None
    events = []
    error = None
    tracking_id = ''

    if request.method == 'POST':
        tracking_id = request.form.get('tracking_id', '').strip().upper()
        if not tracking_id:
            error = 'Please enter a tracking number.'
        else:
            conn = get_db()
            shipment = conn.execute(
                "SELECT * FROM shipments WHERE tracking_id = ?", (tracking_id,)
            ).fetchone()
            if shipment:
                events = conn.execute(
                    "SELECT * FROM tracking_events WHERE shipment_id = ? ORDER BY timestamp ASC",
                    (shipment['id'],)
                ).fetchall()
            else:
                error = f'No shipment found for tracking number <strong>{tracking_id}</strong>. Please verify and try again.'
            conn.close()

    return render_template('track.html', title='Track Your Cargo',
                           shipment=shipment, events=events,
                           error=error, tracking_id=tracking_id)

# ─── Admin Login ──────────────────────────────────────────────────────────────

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db()
        user = conn.execute(
            "SELECT * FROM admin_users WHERE username=? AND password=?", (username, password)
        ).fetchone()
        conn.close()
        if user:
            session['admin_logged_in'] = True
            session['admin_username'] = username
            flash('Welcome back! You are now logged in.', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('admin_login.html', title='Admin Login')

@app.route('/admin/logout')
def admin_logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('admin_login'))

# ─── Admin Dashboard ──────────────────────────────────────────────────────────

@app.route('/admin')
@login_required
def admin_dashboard():
    conn = get_db()
    shipments = conn.execute(
        "SELECT * FROM shipments ORDER BY created_at DESC"
    ).fetchall()
    stats = {
        'total': conn.execute("SELECT COUNT(*) FROM shipments").fetchone()[0],
        'in_transit': conn.execute("SELECT COUNT(*) FROM shipments WHERE status='In Transit'").fetchone()[0],
        'delivered': conn.execute("SELECT COUNT(*) FROM shipments WHERE status='Delivered'").fetchone()[0],
        'customs': conn.execute("SELECT COUNT(*) FROM shipments WHERE status='Customs Clearance'").fetchone()[0],
    }
    conn.close()
    return render_template('admin_dashboard.html', title='Admin Dashboard',
                           shipments=shipments, stats=stats, status_list=STATUS_LIST)

# ─── Admin: Create Shipment ───────────────────────────────────────────────────

@app.route('/admin/shipments/new', methods=['GET', 'POST'])
@login_required
def admin_new_shipment():
    if request.method == 'POST':
        tracking_id = 'KL-' + datetime.now().strftime('%Y') + '-' + str(uuid.uuid4())[:6].upper()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            conn = get_db()
            conn.execute('''
                INSERT INTO shipments (tracking_id, shipper_name, consignee_name, origin, destination,
                    description, weight, volume, status, created_at, updated_at, est_delivery, mode)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                tracking_id,
                request.form['shipper_name'],
                request.form['consignee_name'],
                request.form['origin'],
                request.form['destination'],
                request.form['description'],
                float(request.form.get('weight', 0) or 0),
                float(request.form.get('volume', 0) or 0),
                request.form.get('status', 'Booking Confirmed'),
                now, now,
                request.form.get('est_delivery', ''),
                request.form.get('mode', 'Sea Freight')
            ))
            ship_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            # Auto-create first event
            conn.execute('''
                INSERT INTO tracking_events (shipment_id, event_status, location, notes, timestamp)
                VALUES (?,?,?,?,?)
            ''', (ship_id, 'Booking Confirmed', 'Kalstone Office, Dar es Salaam',
                  'Shipment booking created and confirmed.', now))
            conn.commit()
            conn.close()
            flash(f'Shipment created! Tracking ID: <strong>{tracking_id}</strong>', 'success')
            return redirect(url_for('admin_dashboard'))
        except Exception as e:
            flash(f'Error creating shipment: {str(e)}', 'danger')
    return render_template('admin_shipment_form.html', title='New Shipment',
                           shipment=None, status_list=STATUS_LIST, modes=TRANSPORT_MODES)

# ─── Admin: Edit Shipment ─────────────────────────────────────────────────────

@app.route('/admin/shipments/<int:ship_id>/edit', methods=['GET', 'POST'])
@login_required
def admin_edit_shipment(ship_id):
    conn = get_db()
    shipment = conn.execute("SELECT * FROM shipments WHERE id=?", (ship_id,)).fetchone()
    if not shipment:
        conn.close()
        flash('Shipment not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute('''
            UPDATE shipments SET shipper_name=?, consignee_name=?, origin=?, destination=?,
                description=?, weight=?, volume=?, status=?, updated_at=?, est_delivery=?, mode=?
            WHERE id=?
        ''', (
            request.form['shipper_name'],
            request.form['consignee_name'],
            request.form['origin'],
            request.form['destination'],
            request.form['description'],
            float(request.form.get('weight', 0) or 0),
            float(request.form.get('volume', 0) or 0),
            request.form.get('status', shipment['status']),
            now,
            request.form.get('est_delivery', ''),
            request.form.get('mode', 'Sea Freight'),
            ship_id
        ))
        conn.commit()
        conn.close()
        flash('Shipment updated successfully.', 'success')
        return redirect(url_for('admin_view_shipment', ship_id=ship_id))

    events = conn.execute(
        "SELECT * FROM tracking_events WHERE shipment_id=? ORDER BY timestamp ASC", (ship_id,)
    ).fetchall()
    conn.close()
    return render_template('admin_shipment_form.html', title='Edit Shipment',
                           shipment=shipment, events=events,
                           status_list=STATUS_LIST, modes=TRANSPORT_MODES)

# ─── Admin: View Shipment ─────────────────────────────────────────────────────

@app.route('/admin/shipments/<int:ship_id>')
@login_required
def admin_view_shipment(ship_id):
    conn = get_db()
    shipment = conn.execute("SELECT * FROM shipments WHERE id=?", (ship_id,)).fetchone()
    if not shipment:
        conn.close()
        flash('Shipment not found.', 'danger')
        return redirect(url_for('admin_dashboard'))
    events = conn.execute(
        "SELECT * FROM tracking_events WHERE shipment_id=? ORDER BY timestamp ASC", (ship_id,)
    ).fetchall()
    conn.close()
    return render_template('admin_shipment_detail.html', title=f'Shipment {shipment["tracking_id"]}',
                           shipment=shipment, events=events, status_list=STATUS_LIST)

# ─── Admin: Add Tracking Event ────────────────────────────────────────────────

@app.route('/admin/shipments/<int:ship_id>/add_event', methods=['POST'])
@login_required
def admin_add_event(ship_id):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    event_status = request.form.get('event_status', '')
    location = request.form.get('location', '')
    notes = request.form.get('notes', '')
    timestamp = request.form.get('timestamp', now)

    conn = get_db()
    conn.execute('''
        INSERT INTO tracking_events (shipment_id, event_status, location, notes, timestamp)
        VALUES (?,?,?,?,?)
    ''', (ship_id, event_status, location, notes, timestamp))
    # Also update shipment status to latest event
    conn.execute("UPDATE shipments SET status=?, updated_at=? WHERE id=?",
                 (event_status, now, ship_id))
    conn.commit()
    conn.close()
    flash('Tracking event added successfully.', 'success')
    return redirect(url_for('admin_view_shipment', ship_id=ship_id))

# ─── Admin: Delete Shipment ───────────────────────────────────────────────────

@app.route('/admin/shipments/<int:ship_id>/delete', methods=['POST'])
@login_required
def admin_delete_shipment(ship_id):
    conn = get_db()
    conn.execute("DELETE FROM tracking_events WHERE shipment_id=?", (ship_id,))
    conn.execute("DELETE FROM shipments WHERE id=?", (ship_id,))
    conn.commit()
    conn.close()
    flash('Shipment deleted.', 'info')
    return redirect(url_for('admin_dashboard'))

# ─── Admin: Delete Event ──────────────────────────────────────────────────────

@app.route('/admin/events/<int:event_id>/delete', methods=['POST'])
@login_required
def admin_delete_event(event_id):
    conn = get_db()
    event = conn.execute("SELECT shipment_id FROM tracking_events WHERE id=?", (event_id,)).fetchone()
    ship_id = event['shipment_id'] if event else None
    conn.execute("DELETE FROM tracking_events WHERE id=?", (event_id,))
    conn.commit()
    conn.close()
    flash('Tracking event removed.', 'info')
    if ship_id:
        return redirect(url_for('admin_view_shipment', ship_id=ship_id))
    return redirect(url_for('admin_dashboard'))

# ─── API: Quick Track (JSON) ──────────────────────────────────────────────────

@app.route('/api/track/<tracking_id>')
def api_track(tracking_id):
    conn = get_db()
    shipment = conn.execute(
        "SELECT * FROM shipments WHERE tracking_id=?", (tracking_id.upper(),)
    ).fetchone()
    if not shipment:
        conn.close()
        return jsonify({'error': 'Not found'}), 404
    events = conn.execute(
        "SELECT * FROM tracking_events WHERE shipment_id=? ORDER BY timestamp ASC",
        (shipment['id'],)
    ).fetchall()
    conn.close()
    return jsonify({
        'shipment': dict(shipment),
        'events': [dict(e) for e in events]
    })


# ─── GitHub Webhook Auto-Deploy ───────────────────────────────────────────────

@app.route('/webhook/deploy', methods=['POST'])
def webhook_deploy():
    """Receives GitHub push webhook and auto-deploys the latest code."""
    # Verify signature
    sig_header = request.headers.get('X-Hub-Signature-256', '')
    if not sig_header:
        return jsonify({'error': 'Missing signature'}), 401

    body = request.get_data()
    expected = 'sha256=' + hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected, sig_header):
        return jsonify({'error': 'Invalid signature'}), 403

    # Only deploy on push to main
    payload = request.get_json(silent=True) or {}
    ref = payload.get('ref', '')
    if ref != 'refs/heads/main':
        return jsonify({'message': f'Ignored ref: {ref}'}), 200

    # Run git pull and restart
    app_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        result = subprocess.run(
            ['git', 'pull', 'origin', 'main'],
            cwd=app_dir, capture_output=True, text=True, timeout=60
        )
        # Touch restart.txt to trigger Passenger reload
        restart_dir = os.path.join(app_dir, 'tmp')
        os.makedirs(restart_dir, exist_ok=True)
        open(os.path.join(restart_dir, 'restart.txt'), 'w').close()

        return jsonify({
            'message': 'Deployed successfully',
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
