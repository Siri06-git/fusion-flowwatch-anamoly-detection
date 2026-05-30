import sys
import pandas as pd
import numpy as np


class FlowWatchAIEngine:
    """
    AI Anomaly Engine for the FlowWatch Portal.
    Loads educational engagement records and computes dynamic risk scores
    using weighted normalization on the top 15 behavioral indicators,
    plus an Isolation Forest model for anomaly flagging.
    """

    # Top 15 driver columns with weights and risk directions.
    # positive_risk=True  → higher value = MORE risky  (e.g. days_since_last_login)
    # positive_risk=False → higher value = LESS risky  (e.g. composite_engagement)
    DRIVERS = {
        'weeks_of_quiz_decline':    {'weight': 15, 'positive_risk': True},
        'days_since_last_login':    {'weight': 15, 'positive_risk': True},
        'composite_engagement':     {'weight': 15, 'positive_risk': False},
        'login_count_7d_zscore':    {'weight': 10, 'positive_risk': False},
        'login_count_7d':           {'weight':  8, 'positive_risk': False},
        'login_velocity':           {'weight':  8, 'positive_risk': False},
        'avg_quiz_score':           {'weight':  8, 'positive_risk': False},
        'avg_submission_delay_hours': {'weight': 7, 'positive_risk': True},
        'submission_rate':          {'weight':  7, 'positive_risk': False},
        'session_velocity':         {'weight':  5, 'positive_risk': False},
        'avg_session_duration_min': {'weight':  5, 'positive_risk': False},
        'quiz_velocity':            {'weight':  5, 'positive_risk': False},
        'login_change':             {'weight':  4, 'positive_risk': False},
        'quiz_change':              {'weight':  4, 'positive_risk': False},
        'forum_posts_7d':           {'weight':  4, 'positive_risk': False},
    }

    ALL_NUMERIC_COLS = [
        'login_count_7d', 'avg_session_duration_min', 'days_since_last_login',
        'submission_rate', 'avg_submission_delay_hours', 'forum_posts_7d',
        'avg_quiz_score', 'dropped_out', 'login_lag2', 'session_lag2',
        'quiz_lag2', 'login_change', 'session_change', 'quiz_change',
        'login_count_7d_roll4', 'avg_session_duration_min_roll4',
        'avg_quiz_score_roll4', 'submission_rate_roll4', 'login_velocity',
        'session_velocity', 'quiz_velocity', 'login_count_7d_zscore',
        'avg_session_duration_min_zscore', 'avg_quiz_score_zscore',
        'submission_rate_zscore', 'weeks_of_quiz_decline', 'composite_engagement',
    ]

    def __init__(self, filepath):
        self.filepath = filepath

    def process_anomalies(self):
        """
        Full pipeline: load → clean → score → tier → IsolationForest → return df.
        """
        # ── 1. Load ──────────────────────────────────────────────────────────
        df = pd.read_csv(self.filepath)
        uploaded_rows = len(df)
        print(f"[FlowWatch] Uploaded rows: {uploaded_rows}", file=sys.stderr)

        # ── 2. Clean identity columns ────────────────────────────────────────
        df['student_id'] = df['student_id'].astype(str).str.strip()
        df['week_number'] = (
            pd.to_numeric(df['week_number'], errors='coerce').fillna(1).astype(int)
        )

        # ── 3. Coerce all numeric columns, fill NaN → 0 ─────────────────────
        for col in self.ALL_NUMERIC_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

        # ── 4. Sort for reproducibility ──────────────────────────────────────
        df = df.sort_values(['student_id', 'week_number']).reset_index(drop=True)

        # ── 5. Weighted anomaly scoring (0-100) ──────────────────────────────
        total_weight = sum(v['weight'] for v in self.DRIVERS.values())
        weighted_scores = pd.DataFrame(0.0, index=df.index, columns=list(self.DRIVERS.keys()))

        for col, info in self.DRIVERS.items():
            if col not in df.columns:
                continue
            series = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
            col_min, col_max = series.min(), series.max()
            span = col_max - col_min
            if span > 0:
                if info['positive_risk']:
                    normalized = (series - col_min) / span
                else:
                    normalized = (col_max - series) / span
                weighted_scores[col] = normalized.clip(0.0, 1.0) * info['weight']

        df['anomaly_score'] = (weighted_scores.sum(axis=1) / total_weight) * 100.0

        # ── 6. risk_level (based on raw anomaly_score) ───────────────────────
        def _risk_level(s):
            return 'High' if s >= 70 else ('Medium' if s >= 40 else 'Low')

        df['risk_level'] = df['anomaly_score'].apply(_risk_level)

        # ── 7. risk_score (MinMaxScaler → 0-100) + risk_tier ────────────────
        try:
            from sklearn.preprocessing import MinMaxScaler
            if len(df) > 1 and df['anomaly_score'].max() > df['anomaly_score'].min():
                scaler = MinMaxScaler(feature_range=(0, 100))
                df['risk_score'] = scaler.fit_transform(df[['anomaly_score']]).flatten()
            else:
                df['risk_score'] = df['anomaly_score'].clip(0.0, 100.0)
        except Exception as e:
            df['risk_score'] = df['anomaly_score'].clip(0.0, 100.0)
            print(f"[FlowWatch] MinMaxScaler failed: {e}", file=sys.stderr)

        def _risk_tier(s):
            return 'High' if s >= 70 else ('Medium' if s >= 45 else 'Low')

        df['risk_tier'] = df['risk_score'].apply(_risk_tier)

        # ── 8. Isolation Forest ──────────────────────────────────────────────
        try:
            from sklearn.ensemble import IsolationForest
            feature_cols = [c for c in self.DRIVERS.keys() if c in df.columns]
            X = df[feature_cols].copy()
            clf = IsolationForest(contamination=0.15, random_state=42)
            clf.fit(X)
            raw_if = -clf.decision_function(X)
            if_min, if_max = raw_if.min(), raw_if.max()
            df['anomaly_score_if'] = (
                ((raw_if - if_min) / (if_max - if_min)) * 100.0
                if (if_max - if_min) > 0 else 0.0
            )
            df['is_anomaly'] = (clf.predict(X) == -1).astype(int)
        except Exception as e:
            df['anomaly_score_if'] = 0.0
            df['is_anomaly'] = 0
            print(f"[FlowWatch] IsolationForest failed: {e}", file=sys.stderr)

        # ── 9. Debug summary ─────────────────────────────────────────────────
        processed_rows = len(df)
        anomaly_count = int(df['is_anomaly'].sum())
        tier_counts = df['risk_tier'].value_counts().to_dict()
        print(f"[FlowWatch] Processed rows : {processed_rows}", file=sys.stderr)
        print(f"[FlowWatch] Anomaly count  : {anomaly_count}", file=sys.stderr)
        print(f"[FlowWatch] Risk tiers     : {tier_counts}", file=sys.stderr)

        return df
