from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

class Student(db.Model):
    __tablename__ = 'students'
    
    student_id = db.Column(db.String(50), primary_key=True)
    latest_risk_level = db.Column(db.String(20), default='Low')
    latest_risk_tier = db.Column(db.String(20), default='Low')
    is_flagged = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text, nullable=True)
    
    # Institution metadata (Phase 45)
    year = db.Column(db.Integer, nullable=True)
    branch = db.Column(db.String(100), nullable=True)
    course = db.Column(db.String(100), nullable=True)
    
    # Relationships
    records = db.relationship('EngagementRecord', backref='student', lazy=True, cascade="all, delete-orphan")
    tasks = db.relationship('AdvisorTask', backref='student', lazy=True, cascade="all, delete-orphan")

class EngagementRecord(db.Model):
    __tablename__ = 'engagement_records'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.String(50), db.ForeignKey('students.student_id'), nullable=False)
    week_number = db.Column(db.Integer, nullable=False)
    
    # Standard CSV Columns
    login_count_7d = db.Column(db.Integer)
    avg_session_duration_min = db.Column(db.Float)
    days_since_last_login = db.Column(db.Integer)
    submission_rate = db.Column(db.Float)
    avg_submission_delay_hours = db.Column(db.Float)
    forum_posts_7d = db.Column(db.Integer)
    avg_quiz_score = db.Column(db.Float)
    dropped_out = db.Column(db.Integer)
    
    # Institution metadata (Phase 45)
    year = db.Column(db.Integer, nullable=True)
    branch = db.Column(db.String(100), nullable=True)
    course = db.Column(db.String(100), nullable=True)
    
    # Lags & Changes
    login_lag2 = db.Column(db.Integer)
    session_lag2 = db.Column(db.Float)
    quiz_lag2 = db.Column(db.Float)
    login_change = db.Column(db.Float)
    session_change = db.Column(db.Float)
    quiz_change = db.Column(db.Float)
    
    # Rolling Metrics
    login_count_7d_roll4 = db.Column(db.Float)
    avg_session_duration_min_roll4 = db.Column(db.Float)
    avg_quiz_score_roll4 = db.Column(db.Float)
    submission_rate_roll4 = db.Column(db.Float)
    
    # Velocity & Z-Scores
    login_velocity = db.Column(db.Float)
    session_velocity = db.Column(db.Float)
    quiz_velocity = db.Column(db.Float)
    login_count_7d_zscore = db.Column(db.Float)
    avg_session_duration_min_zscore = db.Column(db.Float)
    avg_quiz_score_zscore = db.Column(db.Float)
    submission_rate_zscore = db.Column(db.Float)
    
    # Decline & Composite Engagement
    weeks_of_quiz_decline = db.Column(db.Integer)
    composite_engagement = db.Column(db.Float)
    
    # Custom Calculated Metrics
    anomaly_score = db.Column(db.Float, default=0.0)
    risk_level = db.Column(db.String(20), default='Low')
    anomaly_score_if = db.Column(db.Float, default=0.0)
    is_anomaly = db.Column(db.Integer, default=0)
    risk_score = db.Column(db.Float, default=0.0)
    risk_tier = db.Column(db.String(20), default='Low')

class AdvisorTask(db.Model):
    __tablename__ = 'advisor_tasks'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    student_id = db.Column(db.String(50), db.ForeignKey('students.student_id'), nullable=False)
    task_description = db.Column(db.String(255), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def SessionLocal():
    return db.session

def init_db():
    db.create_all()
    # Check and add missing columns to students and engagement_records if they don't exist
    engine = db.engine
    with engine.connect() as conn:
        # Check students columns
        try:
            cursor = conn.execute(db.text("PRAGMA table_info(students)"))
            students_cols = [row[1] for row in cursor.fetchall()]
        except Exception:
            students_cols = []
        
        # Check engagement_records columns
        try:
            cursor = conn.execute(db.text("PRAGMA table_info(engagement_records)"))
            records_cols = [row[1] for row in cursor.fetchall()]
        except Exception:
            records_cols = []
        
        # Alter students table
        if students_cols:
            if 'year' not in students_cols:
                conn.execute(db.text("ALTER TABLE students ADD COLUMN year INTEGER"))
            if 'branch' not in students_cols:
                conn.execute(db.text("ALTER TABLE students ADD COLUMN branch VARCHAR(100)"))
            if 'course' not in students_cols:
                conn.execute(db.text("ALTER TABLE students ADD COLUMN course VARCHAR(100)"))
            
        # Alter engagement_records table
        if records_cols:
            if 'year' not in records_cols:
                conn.execute(db.text("ALTER TABLE engagement_records ADD COLUMN year INTEGER"))
            if 'branch' not in records_cols:
                conn.execute(db.text("ALTER TABLE engagement_records ADD COLUMN branch VARCHAR(100)"))
            if 'course' not in records_cols:
                conn.execute(db.text("ALTER TABLE engagement_records ADD COLUMN course VARCHAR(100)"))
        conn.commit()
