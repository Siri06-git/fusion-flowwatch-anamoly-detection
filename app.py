import os
import sys
import traceback
import functools
from flask import Flask, render_template, g, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from database import db, User, Student, EngagementRecord, init_db, SessionLocal
from ai_engine import FlowWatchAIEngine

app = Flask(__name__)

# ── Configuration ────────────────────────────────────────────────────────────
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'flowwatch.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'flowwatch-portal-secret-key-12345'

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'csv'}

REQUIRED_COLUMNS = [
    'student_id', 'week_number', 'login_count_7d', 'avg_session_duration_min',
    'days_since_last_login', 'submission_rate', 'avg_submission_delay_hours',
    'forum_posts_7d', 'avg_quiz_score', 'dropped_out', 'login_lag2',
    'session_lag2', 'quiz_lag2', 'login_change', 'session_change',
    'quiz_change', 'login_count_7d_roll4', 'avg_session_duration_min_roll4',
    'avg_quiz_score_roll4', 'submission_rate_roll4', 'login_velocity',
    'session_velocity', 'quiz_velocity', 'login_count_7d_zscore',
    'avg_session_duration_min_zscore', 'avg_quiz_score_zscore',
    'submission_rate_zscore', 'weeks_of_quiz_decline', 'composite_engagement',
]

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ── Database ──────────────────────────────────────────────────────────────────
db.init_app(app)
with app.app_context():
    init_db()

def get_db():
    if 'db' not in g:
        g.db = SessionLocal()
    return g.db

@app.teardown_appcontext
def teardown_db(exception):
    db_session = g.pop('db', None)
    if db_session is not None:
        db_session.close()

# ── Auth helpers ──────────────────────────────────────────────────────────────
def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if 'user_id' not in session:
            return redirect(url_for('home'))
        return view(**kwargs)
    return wrapped_view

@app.context_processor
def inject_user():
    return dict(
        current_user=session.get('username'),
        user_mode=session.get('portal_mode', '')
    )

# ── Helper: parse processed_cache.csv → metrics dict ─────────────────────────
def _load_cache_metrics():
    """
    Reads uploads/processed_cache.csv and returns a dict with all dashboard
    metrics. Returns a dict of zeroes/empty-lists if the file is absent.
    """
    import pandas as pd

    defaults = dict(
        cohort_size=0,
        high_risk_count=0,
        medium_risk_count=0,
        low_risk_count=0,
        anomaly_count=0,
        avg_engagement=0.0,
        latest_week=0,
        students=[],
    )

    cache_path = os.path.join(app.config['UPLOAD_FOLDER'], 'processed_cache.csv')
    if not os.path.exists(cache_path):
        print("[FlowWatch] processed_cache.csv not found – returning empty metrics", file=sys.stderr)
        return defaults

    try:
        df = pd.read_csv(cache_path)
        print(f"[FlowWatch] Cache loaded: {len(df)} rows, {df['student_id'].nunique()} unique students", file=sys.stderr)

        # Coerce types so comparisons are safe
        df['week_number'] = pd.to_numeric(df['week_number'], errors='coerce').fillna(0).astype(int)
        df['risk_score']  = pd.to_numeric(df['risk_score'],  errors='coerce').fillna(0.0)
        df['composite_engagement'] = pd.to_numeric(df['composite_engagement'], errors='coerce').fillna(0.0)
        df['is_anomaly']  = pd.to_numeric(df['is_anomaly'],  errors='coerce').fillna(0).astype(int)
        df['risk_tier']   = df['risk_tier'].astype(str).str.strip()
        df['student_id']  = df['student_id'].astype(str).str.strip()

        # Handle optional metadata columns for Phase 45
        if 'year' in df.columns:
            df['year'] = pd.to_numeric(df['year'], errors='coerce')
        else:
            df['year'] = None
            
        if 'branch' in df.columns:
            df['branch'] = df['branch'].astype(str).str.strip().replace('nan', '')
        else:
            df['branch'] = None

        if 'course' in df.columns:
            df['course'] = df['course'].astype(str).str.strip().replace('nan', '')
        else:
            df['course'] = None

        cohort_size  = int(df['student_id'].nunique())
        latest_week  = int(df['week_number'].max())
        anomaly_count = int(df['is_anomaly'].sum())

        # Use all rows in the latest week for KPIs
        df_latest = df[df['week_number'] == latest_week].copy()
        print(f"[FlowWatch] Latest week={latest_week}, rows={len(df_latest)}", file=sys.stderr)

        high_risk_count   = int((df_latest['risk_tier'] == 'High').sum())
        medium_risk_count = int((df_latest['risk_tier'] == 'Medium').sum())
        low_risk_count    = int((df_latest['risk_tier'] == 'Low').sum())
        avg_engagement    = round(float(df_latest['composite_engagement'].mean()), 2) if not df_latest.empty else 0.0

        print(f"[FlowWatch] KPIs → total={cohort_size}, high={high_risk_count}, "
              f"medium={medium_risk_count}, low={low_risk_count}, anomalies={anomaly_count}", file=sys.stderr)

        # Build the students table (sorted by risk_score desc)
        df_table = df_latest.sort_values('risk_score', ascending=False)
        students = df_table.to_dict(orient='records')

        return dict(
            cohort_size=cohort_size,
            high_risk_count=high_risk_count,
            medium_risk_count=medium_risk_count,
            low_risk_count=low_risk_count,
            anomaly_count=anomaly_count,
            avg_engagement=avg_engagement,
            latest_week=latest_week,
            students=students,
        )
    except Exception:
        print("[FlowWatch] ERROR loading cache:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return defaults

def _mode_home():
    """Returns the correct dashboard url_for string based on portal_mode."""
    if session.get('portal_mode') == 'institution':
        return url_for('institution_dashboard')
    return url_for('dashboard')


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def home():
    if 'user_id' in session:
        if 'portal_mode' not in session:
            return redirect(url_for('choose_mode'))
        return redirect(_mode_home())
    active_tab = request.args.get('tab', 'login')
    return render_template('home.html', active_tab=active_tab)

@app.route('/upload')
@login_required
def upload():
    return render_template('index.html')

@app.route('/institution-dashboard')
@login_required
def institution_dashboard():
    """Academic-focused dashboard for Institution mode users."""
    # Redirect Industry users away
    if session.get('portal_mode') != 'institution':
        return redirect(url_for('dashboard'))
    metrics = _load_cache_metrics()
    return render_template('institution_dashboard.html', **metrics)

@app.route('/dashboard')
@login_required
def dashboard():
    """Industry dashboard – shows live KPIs, risk breakdown, top-risk students."""
    # Redirect Institution users to their dashboard
    if session.get('portal_mode') == 'institution':
        return redirect(url_for('institution_dashboard'))
    metrics = _load_cache_metrics()
    return render_template('dashboard.html', **metrics)

@app.route('/analytics')
@login_required
def analytics():
    """Renders the analytics cockpit, reading metrics from processed_cache.csv."""
    metrics = _load_cache_metrics()
    return render_template('analytics.html', **metrics)

@app.route('/profile')
@login_required
def profile():
    student_id = request.args.get('student_id', '').strip()
    history_list = []
    error_msg = None

    student_meta = None
    if student_id:
        session_db = get_db()
        student_obj = session_db.query(Student).filter_by(student_id=student_id).first()
        if student_obj:
            student_meta = {
                'year': student_obj.year,
                'branch': student_obj.branch,
                'course': student_obj.course
            }

        records = (session_db.query(EngagementRecord)
                   .filter_by(student_id=student_id)
                   .order_by(EngagementRecord.week_number)
                   .all())
        if not records:
            error_msg = f"No record history found for student ID: '{student_id}'"
        else:
            for r in records:
                history_list.append({
                    'week_number':         int(r.week_number),
                    'risk_score':          round(float(r.risk_score or 0.0), 1),
                    'risk_tier':           r.risk_tier,
                    'avg_quiz_score':      round(float(r.avg_quiz_score or 0.0), 2),
                    'composite_engagement': round(float(r.composite_engagement or 0.0), 2),
                })

    return render_template('profile.html',
                           student_id=student_id,
                           history=history_list,
                           error_msg=error_msg,
                           student_meta=student_meta)

@app.route('/api/student/<student_id>/history')
@login_required
def student_history(student_id):
    session_db = get_db()
    records = (session_db.query(EngagementRecord)
               .filter_by(student_id=student_id)
               .order_by(EngagementRecord.week_number)
               .all())
    history = [
        {
            'week_number':          int(r.week_number),
            'composite_engagement': float(r.composite_engagement or 0.0),
            'avg_quiz_score':       float(r.avg_quiz_score or 0.0),
            'days_since_last_login': int(r.days_since_last_login or 0),
            'risk_score':           float(r.risk_score or 0.0),
        }
        for r in records
    ]
    return jsonify(history)

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    if not username or not password:
        flash('Both username and password are required.', 'error')
        return redirect(url_for('home', tab='register'))
    session_db = get_db()
    if session_db.query(User).filter_by(username=username).first():
        flash('Username is already taken.', 'error')
        return redirect(url_for('home', tab='register'))
    session_db.add(User(username=username, password_hash=generate_password_hash(password)))
    session_db.commit()
    flash('Account registered successfully! Please log in.', 'success')
    return redirect(url_for('home', tab='login'))

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    session_db = get_db()
    user = session_db.query(User).filter_by(username=username).first()
    if user is None or not check_password_hash(user.password_hash, password):
        flash('Invalid username or password.', 'error')
        return redirect(url_for('home', tab='login'))
    session.clear()
    session['user_id'] = user.id
    session['username'] = user.username
    flash('Welcome back to FlowWatch Portal!', 'success')
    return redirect(url_for('choose_mode'))

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('home'))

@app.route('/choose-mode')
@login_required
def choose_mode():
    """Mode selection page shown once after login."""
    return render_template('choose_mode.html')

@app.route('/set-mode', methods=['POST'])
@login_required
def set_mode():
    """Stores the chosen mode in session as portal_mode and routes accordingly."""
    mode = request.form.get('mode', '').strip().lower()
    if mode not in ('institution', 'industry'):
        flash('Please select a valid mode.', 'error')
        return redirect(url_for('choose_mode'))
    session['portal_mode'] = mode
    flash(f'Mode set to {mode.capitalize()}. Welcome!', 'success')
    # Route Institution → institution dashboard, Industry → industry dashboard
    return redirect(_mode_home())

# ── CSV Upload ────────────────────────────────────────────────────────────────
@app.route('/upload-csv', methods=['POST'])
@login_required
def upload_csv():
    """Validates, AI-processes, and caches the uploaded CSV."""
    import pandas as pd

    if 'file' not in request.files:
        flash('No file part in the request.', 'error')
        return redirect(url_for('analytics'))

    file = request.files['file']
    if not file or file.filename == '':
        flash('No file selected.', 'error')
        return redirect(url_for('analytics'))

    if not allowed_file(file.filename):
        flash('Only CSV files are supported.', 'error')
        return redirect(url_for('analytics'))

    filename  = secure_filename(file.filename)
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(save_path)
    print(f"[FlowWatch] Saved upload to: {save_path}", file=sys.stderr)

    # ── Step 1: Column validation ─────────────────────────────────────────
    try:
        df_headers = pd.read_csv(save_path, nrows=0)
        csv_columns = set(df_headers.columns.str.strip())
        
        required = list(REQUIRED_COLUMNS)
        if session.get('portal_mode') == 'institution':
            required.extend(['year', 'branch', 'course'])
            
        missing = [c for c in required if c not in csv_columns]
        if missing:
            os.remove(save_path)
            flash(f"Upload failed – missing columns: {', '.join(missing)}", 'error')
            return redirect(url_for('analytics'))
        print(f"[FlowWatch] Column check passed. Columns found: {list(csv_columns)}", file=sys.stderr)
    except Exception:
        if os.path.exists(save_path):
            os.remove(save_path)
        flash(f"Could not read CSV headers: {traceback.format_exc(limit=1)}", 'error')
        return redirect(url_for('analytics'))

    # ── Step 2: AI processing ─────────────────────────────────────────────
    try:
        engine = FlowWatchAIEngine(save_path)
        df_processed = engine.process_anomalies()
        print(f"[FlowWatch] AI engine returned {len(df_processed)} rows", file=sys.stderr)
        print(f"[FlowWatch] Columns: {list(df_processed.columns)}", file=sys.stderr)
    except Exception:
        if os.path.exists(save_path):
            os.remove(save_path)
        err = traceback.format_exc()
        print(f"[FlowWatch] AI engine ERROR:\n{err}", file=sys.stderr)
        flash(f"AI engine failed: {err}", 'error')
        return redirect(url_for('analytics'))

    # ── Step 3: Save processed cache ──────────────────────────────────────
    try:
        cache_path = os.path.join(app.config['UPLOAD_FOLDER'], 'processed_cache.csv')
        df_processed.to_csv(cache_path, index=False)
        print(f"[FlowWatch] Cache saved → {cache_path} ({os.path.getsize(cache_path)} bytes)", file=sys.stderr)
    except Exception:
        err = traceback.format_exc()
        print(f"[FlowWatch] Cache write ERROR:\n{err}", file=sys.stderr)
        flash(f"Cache write failed: {err}", 'error')
        return redirect(url_for('analytics'))

    # ── Step 4: SQLite ingestion ──────────────────────────────────────────
    try:
        session_db = get_db()
        session_db.query(EngagementRecord).delete()
        session_db.query(Student).delete()
        session_db.commit()

        has_year = 'year' in df_processed.columns
        has_branch = 'branch' in df_processed.columns
        has_course = 'course' in df_processed.columns

        def _clean_str(val):
            if pd.isna(val) or str(val).strip().lower() in ('nan', ''):
                return None
            return str(val).strip()

        def _clean_int(val):
            try:
                if pd.isna(val):
                    return None
                return int(float(val))
            except:
                return None

        for sid in df_processed['student_id'].unique():
            rows = df_processed[df_processed['student_id'] == sid]
            latest = rows.sort_values('week_number').iloc[-1]
            session_db.add(Student(
                student_id=sid,
                latest_risk_level=str(latest.get('risk_level', 'Low')),
                latest_risk_tier=str(latest.get('risk_tier', 'Low')),
                year=_clean_int(latest.get('year')) if has_year else None,
                branch=_clean_str(latest.get('branch')) if has_branch else None,
                course=_clean_str(latest.get('course')) if has_course else None,
            ))
        session_db.commit()

        for _, row in df_processed.iterrows():
            def _int(v, default=0):
                try: return int(v)
                except: return default
            def _float(v, default=0.0):
                try: return float(v)
                except: return default

            r_year = _clean_int(row.get('year')) if has_year else None
            r_branch = _clean_str(row.get('branch')) if has_branch else None
            r_course = _clean_str(row.get('course')) if has_course else None

            session_db.add(EngagementRecord(
                student_id=str(row['student_id']),
                week_number=_int(row['week_number']),
                login_count_7d=_int(row.get('login_count_7d')),
                avg_session_duration_min=_float(row.get('avg_session_duration_min')),
                days_since_last_login=_int(row.get('days_since_last_login')),
                submission_rate=_float(row.get('submission_rate')),
                avg_submission_delay_hours=_float(row.get('avg_submission_delay_hours')),
                forum_posts_7d=_int(row.get('forum_posts_7d')),
                avg_quiz_score=_float(row.get('avg_quiz_score')),
                dropped_out=_int(row.get('dropped_out')),
                login_lag2=_int(row.get('login_lag2')),
                session_lag2=_float(row.get('session_lag2')),
                quiz_lag2=_float(row.get('quiz_lag2')),
                login_change=_float(row.get('login_change')),
                session_change=_float(row.get('session_change')),
                quiz_change=_float(row.get('quiz_change')),
                login_count_7d_roll4=_float(row.get('login_count_7d_roll4')),
                avg_session_duration_min_roll4=_float(row.get('avg_session_duration_min_roll4')),
                avg_quiz_score_roll4=_float(row.get('avg_quiz_score_roll4')),
                submission_rate_roll4=_float(row.get('submission_rate_roll4')),
                login_velocity=_float(row.get('login_velocity')),
                session_velocity=_float(row.get('session_velocity')),
                quiz_velocity=_float(row.get('quiz_velocity')),
                login_count_7d_zscore=_float(row.get('login_count_7d_zscore')),
                avg_session_duration_min_zscore=_float(row.get('avg_session_duration_min_zscore')),
                avg_quiz_score_zscore=_float(row.get('avg_quiz_score_zscore')),
                submission_rate_zscore=_float(row.get('submission_rate_zscore')),
                weeks_of_quiz_decline=_int(row.get('weeks_of_quiz_decline')),
                composite_engagement=_float(row.get('composite_engagement')),
                anomaly_score=_float(row.get('anomaly_score')),
                risk_level=str(row.get('risk_level', 'Low')),
                anomaly_score_if=_float(row.get('anomaly_score_if')),
                is_anomaly=_int(row.get('is_anomaly')),
                risk_score=_float(row.get('risk_score')),
                risk_tier=str(row.get('risk_tier', 'Low')),
                year=r_year,
                branch=r_branch,
                course=r_course,
            ))
        session_db.commit()
        print(f"[FlowWatch] SQLite ingestion complete: {len(df_processed)} rows", file=sys.stderr)

    except Exception:
        err = traceback.format_exc()
        print(f"[FlowWatch] SQLite ERROR:\n{err}", file=sys.stderr)
        flash(f"Database ingestion error: {err}", 'error')
        # Don't redirect yet – the cache is already saved so analytics will still work
    finally:
        if os.path.exists(save_path):
            os.remove(save_path)

    flash(
        f'✅ "{filename}" ingested — {len(df_processed)} records processed, '
        f'{int(df_processed["is_anomaly"].sum())} anomalies detected.',
        'success'
    )
    return redirect(url_for('analytics'))


if __name__ == '__main__':
    app.run(debug=True, port=5000)
