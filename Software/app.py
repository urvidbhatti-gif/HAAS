"""
Hospital Admission Avoidance System (HAAS) – Flask Backend
CN7000 MSc Dissertation – University of East London
Author: Urvi Bhatti | Supervisor: Dr. Rasha Hafidh

ARCHITECTURE:
  - Modular MCDA Engine (decoupled from route handlers)
  - Decision Audit Trail (persistent SQLite logging)
  - Input Validation (type-safe request parsing)
  - Error Boundary Handling (graceful JSON error responses)
  - CETR Policy Engine (deterministic gatekeeping)
  - RESTful API Design (JSON-only, versioned endpoints)

ENDPOINTS:
  GET  /                          → Dashboard UI
  GET  /api/hospitals             → Filtered hospital directory
  GET  /api/stats                 → National intelligence statistics
  POST /api/predict_risk          → Patient risk prediction scoring
  POST /api/check_admission       → CETR admission gatekeeper + MCDA matching
  GET  /api/community_services    → Community services directory
  GET  /api/map_data              → Geospatial map data (hospitals + community)
  GET  /api/audit_log             → Decision audit trail (accountability)
"""
from flask import Flask, render_template, request, jsonify, send_file
import sqlite3
import os
import sys
import io
import json
import hashlib
from datetime import datetime
from functools import wraps
import math
import logging
from fpdf import FPDF

# ────────────────────────────────────────────────────
# Application Setup
# ────────────────────────────────────────────────────
app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'data', 'hospitals.db')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('HAAS')


def ensure_database():
    """Auto-generate the database if it does not exist (zero-fault startup)."""
    if not os.path.exists(DB_PATH):
        logger.warning('Database not found — auto-generating synthetic data…')
        gen_script = os.path.join(BASE_DIR, 'generate_data.py')
        if os.path.exists(gen_script):
            import subprocess
            subprocess.run([sys.executable, gen_script], check=True)
            logger.info('Database generated successfully.')
        else:
            logger.error('generate_data.py not found — cannot auto-recover.')


# ────────────────────────────────────────────────────
# Database Helper
# ────────────────────────────────────────────────────
def get_db():
    """Thread-safe database connection with Row factory."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    except sqlite3.DatabaseError as e:
        logger.error(f'Database connection failed: {e} — attempting recovery…')
        # Attempt recovery by regenerating
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        ensure_database()
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn


def error_response(message, status_code=400):
    """Standardised JSON error response."""
    return jsonify({
        'error': True,
        'message': message,
        'timestamp': datetime.now().isoformat()
    }), status_code


def api_error_handler(f):
    """Decorator for consistent API error handling."""
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as e:
            logger.warning(f"Validation error in {f.__name__}: {e}")
            return error_response(str(e), 400)
        except sqlite3.Error as e:
            logger.error(f"Database error in {f.__name__}: {e}")
            return error_response("Internal database error", 500)
        except Exception as e:
            logger.error(f"Unexpected error in {f.__name__}: {e}")
            return error_response("Internal server error", 500)
    return decorated


# ════════════════════════════════════════════════════
# MCDA ENGINE (Decoupled from Route Handlers)
# ════════════════════════════════════════════════════
class MCDAEngine:
    """Multi-Criteria Decision Analysis Engine for hospital suitability scoring.

    Implements a Weighted Sum Model (WSM) across three weighted pillars
    aligned with the dissertation methodology (Ishizaka & Nemery, 2013):
      Pillar 1: CQC Quality Rating         — 45% (w = 0.45)
      Pillar 2: Specialist Capabilities     — 35% (w = 0.35)
      Pillar 3: Geographic Proximity        — 20% (w = 0.20)

    Total possible score: 100 points.
    """

    # Three-pillar WSM weights as defined in the dissertation (§2.1.10)
    WEIGHTS = {
        'cqc_quality':            45,   # Pillar 1: CQC Rating
        'specialist_capability':  35,   # Pillar 2: Autism + LD + Services
        'geographic_proximity':   20,   # Pillar 3: Distance
    }

    @staticmethod
    def haversine_distance(lat1, lon1, lat2, lon2):
        """Calculate great-circle distance between two GPS points in km."""
        R = 6371  # Earth radius in km
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
        return R * 2 * math.asin(math.sqrt(a))

    @classmethod
    def score_hospital(cls, hospital_row, patient_lat, patient_lon):
        """Calculate Intelligent Match Score (IMS) for a single hospital.

        Applies the three-pillar WSM:
          IMS = w1*CQC + w2*Specialist + w3*Proximity

        Args:
            hospital_row: sqlite3.Row with hospital data
            patient_lat: Patient's latitude
            patient_lon: Patient's longitude

        Returns:
            tuple: (total_score: int, breakdown: dict, distance_km: float)
        """
        score = 0
        breakdown = {}

        # ── Pillar 1: CQC Quality Rating (max 45 points, w=0.45) ──
        cqc = hospital_row['cqc_rating']
        cqc_map = {
            'Outstanding': 45,
            'Good': 30,
            'Requires Improvement': 10,
            'Inadequate': 0,
        }
        cqc_score = cqc_map.get(cqc, 0)
        score += cqc_score
        breakdown['CQC Quality (45%)'] = f"+{cqc_score} ({cqc})"

        # ── Pillar 2: Specialist Capabilities (max 35 points, w=0.35) ──
        spec_score = 0
        spec_details = []

        # Autism Accreditation (15 pts)
        if hospital_row['autism_accredited']:
            spec_score += 15
            spec_details.append('Autism Accredited')

        # LD Specialist Ward (10 pts)
        if hospital_row['ld_specialist_ward']:
            spec_score += 10
            spec_details.append('LD Specialist')

        # Clinical Services — SALT, Sensory Room, OT, Psychology (2.5 each, max 10)
        svc_pts = 0
        services = []
        for col, label in [('has_salt', 'SALT'), ('has_sensory_room', 'Sensory Room'),
                           ('has_ot', 'OT'), ('has_psychology', 'Psychology')]:
            if hospital_row[col]:
                svc_pts += 2.5
                services.append(label)
        svc_pts = min(svc_pts, 10)
        spec_score += int(svc_pts)
        if services:
            spec_details.extend(services)

        spec_score = min(spec_score, cls.WEIGHTS['specialist_capability'])
        score += spec_score
        breakdown['Specialist (35%)'] = (
            f"+{spec_score} ({', '.join(spec_details) if spec_details else 'None'})"
        )

        # ── Pillar 3: Geographic Proximity (max 20 points, w=0.20) ──
        try:
            distance = cls.haversine_distance(
                patient_lat, patient_lon,
                hospital_row['latitude'], hospital_row['longitude']
            )
            if distance < 10:
                dist_score = 20
            elif distance < 25:
                dist_score = 15
            elif distance < 50:
                dist_score = 10
            elif distance < 100:
                dist_score = 5
            else:
                dist_score = 0
            score += dist_score
            breakdown['Proximity (20%)'] = f"+{dist_score} ({distance:.1f}km)"
        except (TypeError, ValueError):
            distance = 999.0

        return score, breakdown, distance


# ════════════════════════════════════════════════════
# CETR POLICY ENGINE (Deterministic Gatekeeper)
# ════════════════════════════════════════════════════
class CETRPolicyEngine:
    """Care Education & Treatment Review policy enforcement.

    Implements NHS England CETR guidelines (2023) for individuals with
    autism and/or learning disabilities. Admission is blocked when:
      - Patient has ASD/LD diagnosis
      - No active, treatable mental illness is present
      - Sensory/environmental triggers have not been ruled out

    Includes Sensory Meltdown Flag (§2.1.4) to differentiate between
    genuine psychiatric emergencies and sensory/environmental crises.
    """

    ASD_LD_KEYWORDS = {'autism', 'asd', 'ld', 'learning di', 'learning_disability'}
    SENSORY_KEYWORDS = {'sensory', 'meltdown', 'overload', 'overstimulation',
                        'noise', 'light', 'environmental', 'shutdown'}

    @classmethod
    def evaluate(cls, age, diagnosis, has_mental_illness, location='',
                 sensory_trigger=False, community_exhausted=True):
        """Evaluate admission eligibility under CETR guidelines.

        Args:
            age: Patient age
            diagnosis: Primary diagnosis string
            has_mental_illness: Whether an active treatable mental illness is present
            location: Patient location for community matching
            sensory_trigger: Whether a sensory/environmental trigger is suspected
            community_exhausted: Whether community alternatives have been exhausted

        Returns:
            dict with keys: avoidance_alert, risk_level, reasons, recommendation,
                            sensory_flag
        """
        diagnosis_lower = diagnosis.lower() if diagnosis else ''
        is_asd_ld = any(kw in diagnosis_lower for kw in cls.ASD_LD_KEYWORDS)

        avoidance_alert = False
        reasons = []
        risk_level = 'LOW'
        sensory_flag = False

        # Sensory Meltdown Flag — differentiate sensory crisis from psychiatric
        if is_asd_ld and (sensory_trigger or
                any(kw in diagnosis_lower for kw in cls.SENSORY_KEYWORDS)):
            sensory_flag = True
            reasons.append(
                '⚠ SENSORY MELTDOWN FLAG: Presentation may indicate '
                'sensory/environmental crisis, NOT a psychiatric emergency. '
                'Rule out environmental antecedents before proceeding (CETR §3.1).'
            )

        if age < 16 and is_asd_ld and not has_mental_illness:
            avoidance_alert = True
            risk_level = 'HIGH'
            reasons.extend([
                f'Patient is under 16 (age: {age}) with Autism/LD '
                'and no treatable mental illness.',
                'CETR Guidelines §4.2: Hospital admission is '
                'INAPPROPRIATE for this profile.',
                f'Recommendation: Community-based support in '
                f'{location or "local area"}.',
            ])
        elif is_asd_ld and not has_mental_illness:
            avoidance_alert = True
            risk_level = 'HIGH'
            reasons.extend([
                'Patient has ASD/LD without co-occurring treatable '
                'mental illness.',
                'CETR §4.2: ASD/LD alone is NOT a legal justification '
                'for psychiatric detention.',
                'HARD STOP: Explore community alternatives before '
                'any bed search can proceed.',
            ])
        elif is_asd_ld and has_mental_illness and not community_exhausted:
            risk_level = 'MEDIUM'
            reasons.append(
                'Patient has ASD/LD with co-occurring mental illness, '
                'but community alternatives have not been exhausted.'
            )

        recommendation = {
            'HIGH': 'ADMISSION BLOCKED — COMMUNITY CARE REQUIRED',
            'MEDIUM': 'REVIEW REQUIRED — Exhaust community options first',
            'LOW': 'HOSPITAL ADMISSION MAY PROCEED',
        }[risk_level]

        return {
            'avoidance_alert': avoidance_alert,
            'risk_level': risk_level,
            'reasons': reasons,
            'recommendation': recommendation,
            'sensory_flag': sensory_flag,
        }


# ════════════════════════════════════════════════════
# AUDIT LOGGER (Clinical Accountability)
# ════════════════════════════════════════════════════
class AuditLogger:
    """Persistent decision audit trail for clinical accountability.

    Every admission decision is logged with full input parameters,
    MCDA scores, and reasoning for regulatory compliance.
    """

    @staticmethod
    def generate_patient_hash(age, diagnosis):
        """Generate a pseudonymised hash for GDPR compliance."""
        raw = f"{age}:{diagnosis}:{datetime.now().date()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def log_decision(conn, patient_age, diagnosis, input_params,
                     decision_type, mcda_score=None, facility_id=None,
                     facility_name=None, reasoning=None):
        """Write a decision record to the audit log."""
        patient_hash = AuditLogger.generate_patient_hash(patient_age, diagnosis)
        conn.execute(
            '''INSERT INTO decision_audit_log
               (patient_hash, patient_age, diagnosis, input_parameters_json,
                decision_type, mcda_suitability_score, matched_facility_id,
                matched_facility_name, reasoning_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (patient_hash, patient_age, diagnosis,
             json.dumps(input_params), decision_type, mcda_score,
             facility_id, facility_name, json.dumps(reasoning or {}))
        )
        conn.commit()
        logger.info(
            f"AUDIT: {decision_type} | age={patient_age} | "
            f"diagnosis={diagnosis} | score={mcda_score}"
        )


# ════════════════════════════════════════════════════
# INPUT VALIDATORS
# ════════════════════════════════════════════════════
def validate_admission_input(data):
    """Validate and sanitise admission check input."""
    if not data:
        raise ValueError("Request body is required")

    age = int(data.get('age', 18))
    if age < 0 or age > 120:
        raise ValueError(f"Invalid age: {age}. Must be 0-120.")

    gender = str(data.get('gender', 'Unspecified')).strip().title()
    diagnosis = str(data.get('diagnosis', '')).strip()
    has_mental_illness = bool(data.get('has_mental_illness', False))
    location = str(data.get('location', '')).strip()
    patient_lat = float(data.get('latitude', 51.5074))
    patient_lon = float(data.get('longitude', -0.1278))

    if not (-90 <= patient_lat <= 90) or not (-180 <= patient_lon <= 180):
        raise ValueError("Invalid coordinates")

    return {
        'age': age,
        'gender': gender,
        'diagnosis': diagnosis,
        'has_mental_illness': has_mental_illness,
        'location': location,
        'latitude': patient_lat,
        'longitude': patient_lon,
    }


def validate_risk_input(data):
    """Validate and sanitise risk prediction input."""
    if not data:
        raise ValueError("Request body is required")

    age = int(data.get('age', 15))
    if age < 0 or age > 120:
        raise ValueError(f"Invalid age: {age}")

    return {
        'age': age,
        'diagnosis': str(data.get('diagnosis', '')).strip().lower(),
        'previous_admissions': max(0, int(data.get('previous_admissions', 0))),
        'challenging_behaviour': bool(data.get('challenging_behaviour', False)),
        'community_support': bool(data.get('community_support', False)),
        'family_coping': bool(data.get('family_coping', True)),
        'school_attendance': bool(data.get('school_attendance', True)),
        'medication_compliance': bool(data.get('medication_compliance', True)),
    }


# ════════════════════════════════════════════════════
# ROUTE HANDLERS
# ════════════════════════════════════════════════════

# ─── HOME PAGE ────────────────────────────────────
@app.route('/')
def index():
    return render_template('index_professional.html')


# ─── API: HOSPITALS DIRECTORY ─────────────────────
@app.route('/api/hospitals', methods=['GET'])
@api_error_handler
def get_hospitals():
    location = request.args.get('location', '')
    rating = request.args.get('rating', '')
    under16 = request.args.get('under16', 'false')
    autism_only = request.args.get('autism', 'false')
    available_only = request.args.get('available', 'false')

    conn = get_db()
    try:
        query = 'SELECT * FROM hospitals WHERE 1=1'
        params = []

        if location:
            safe_loc = location.replace('%', '\\%').replace('_', '\\_')
            query += " AND location LIKE ? ESCAPE '\\'"
            params.append(f'%{safe_loc}%')
        if rating:
            query += ' AND cqc_rating = ?'
            params.append(rating)
        if under16 == 'true':
            query += ' AND age_min <= 12'
        if autism_only == 'true':
            query += ' AND (autism_accredited = 1 OR specialist_beds_autism > 0)'
        if available_only == 'true':
            query += ' AND available_beds > 0'

        hospitals = conn.execute(query, params).fetchall()
        return jsonify([dict(row) for row in hospitals])
    finally:
        conn.close()


# ─── API: DASHBOARD STATS ─────────────────────────
@app.route('/api/stats', methods=['GET'])
@api_error_handler
def get_stats():
    conn = get_db()
    try:
        total = conn.execute('SELECT COUNT(*) FROM hospitals').fetchone()[0]
        under16 = conn.execute(
            'SELECT COUNT(*) FROM hospitals WHERE age_min <= 12'
        ).fetchone()[0]
        good_rated = conn.execute(
            "SELECT COUNT(*) FROM hospitals WHERE cqc_rating IN ('Good','Outstanding')"
        ).fetchone()[0]
        avg_beds = conn.execute('SELECT AVG(total_beds) FROM hospitals').fetchone()[0]
        total_available = conn.execute(
            'SELECT SUM(available_beds) FROM hospitals'
        ).fetchone()[0]
        autism_accredited = conn.execute(
            'SELECT COUNT(*) FROM hospitals WHERE autism_accredited = 1'
        ).fetchone()[0]
        community_services_count = conn.execute(
            'SELECT COUNT(*) FROM community_services'
        ).fetchone()[0]
        community_available = conn.execute(
            'SELECT COUNT(*) FROM community_services WHERE available = 1'
        ).fetchone()[0]

        by_region = conn.execute(
            'SELECT location, COUNT(*) as count FROM hospitals '
            'GROUP BY location ORDER BY count DESC LIMIT 10'
        ).fetchall()
        by_rating = conn.execute(
            'SELECT cqc_rating, COUNT(*) as count FROM hospitals GROUP BY cqc_rating'
        ).fetchall()

        return jsonify({
            'totalHospitals': total,
            'under16Facilities': under16,
            'goodOrOutstanding': good_rated,
            'avgBeds': round(avg_beds, 1) if avg_beds else 0,
            'totalAvailableBeds': total_available or 0,
            'autismAccredited': autism_accredited,
            'communityServices': community_services_count,
            'communityAvailable': community_available,
            'byRegion': [dict(r) for r in by_region],
            'byRating': [dict(r) for r in by_rating],
            'lastUpdated': datetime.now().strftime('%d %b %Y %H:%M')
        })
    finally:
        conn.close()


# ─── API: RISK PREDICTION SCORING ────────────────
@app.route('/api/predict_risk', methods=['POST'])
@api_error_handler
def predict_risk():
    """Predict patient's risk of requiring hospital admission.

    Uses a weighted additive model across six psychosocial risk factors.
    Each factor contributes a fixed score to total risk (max 100).
    """
    params = validate_risk_input(request.json)

    risk_score = 0
    risk_factors_triggered = []

    # Previous admissions (25% weight)
    if params['previous_admissions'] > 0:
        admission_score = min(params['previous_admissions'] * 8, 25)
        risk_score += admission_score
        risk_factors_triggered.append(
            f"Previous admissions: {params['previous_admissions']}"
        )

    # Challenging behaviour (20% weight)
    if params['challenging_behaviour']:
        risk_score += 20
        risk_factors_triggered.append("Frequent challenging behaviour")

    # Lack of community support (18% weight)
    if not params['community_support']:
        risk_score += 18
        risk_factors_triggered.append("No community service engagement")

    # Family stress (15% weight)
    if not params['family_coping']:
        risk_score += 15
        risk_factors_triggered.append("Family unable to cope")

    # School issues (12% weight)
    if not params['school_attendance']:
        risk_score += 12
        risk_factors_triggered.append("School exclusion/non-attendance")

    # Medication (10% weight)
    if not params['medication_compliance']:
        risk_score += 10
        risk_factors_triggered.append("Medication non-compliance")

    # Risk level classification
    if risk_score >= 70:
        risk_level, recommendation, color = (
            "VERY HIGH",
            "URGENT: Intensive community support required immediately",
            "red"
        )
    elif risk_score >= 50:
        risk_level, recommendation, color = (
            "HIGH",
            "Enhanced community support recommended",
            "orange"
        )
    elif risk_score >= 30:
        risk_level, recommendation, color = (
            "MODERATE",
            "Monitor closely, consider preventive interventions",
            "amber"
        )
    else:
        risk_level, recommendation, color = (
            "LOW",
            "Continue current support plan",
            "green"
        )

    return jsonify({
        'riskScore': risk_score,
        'riskLevel': risk_level,
        'color': color,
        'recommendation': recommendation,
        'riskFactors': risk_factors_triggered,
        'timestamp': datetime.now().isoformat()
    })


# ─── API: ADMISSION GATEKEEPER + MCDA ────────────
@app.route('/api/check_admission', methods=['POST'])
@api_error_handler
def check_admission():
    """CETR-compliant admission gatekeeper with MCDA hospital matching.

    Pipeline:
      1. Validate input parameters
      2. Evaluate CETR policy (deterministic gatekeeper)
      3. If blocked → match community services
      4. If approved → run MCDA scoring on eligible hospitals
      5. Log decision to audit trail
    """
    params = validate_admission_input(request.json)

    # Step 1: CETR Policy Evaluation (with Sensory Meltdown Flag)
    policy = CETRPolicyEngine.evaluate(
        params['age'], params['diagnosis'],
        params['has_mental_illness'], params['location'],
        sensory_trigger=params.get('sensory_trigger', False),
        community_exhausted=params.get('community_exhausted', True)
    )

    alternatives = []
    suitable_hospitals = []
    conn = get_db()

    try:
        if policy['avoidance_alert']:
            # Step 2a: Match community services for blocked admissions
            q = '''SELECT * FROM community_services
                   WHERE available = 1 AND age_min <= ? AND age_max >= ?'''
            q_params = [params['age'], params['age']]
            if params.get('gender') in ['Male', 'Female']:
                q += " AND gender_restriction IN ('Mixed', ?)"
                q_params.append(f"{params['gender']} Only")
                
            if params['location']:
                q += ' AND location LIKE ?'
                q_params.append(f"%{params['location']}%")
            q += ' ORDER BY crisis_support DESC, capacity - current_load DESC LIMIT 5'

            for row in conn.execute(q, q_params).fetchall():
                alternatives.append({
                    'name': row['name'],
                    'type': row['service_type'],
                    'location': row['location'],
                    'availability': f"{row['capacity'] - row['current_load']} spaces",
                    'contact': row['contact_number'],
                    'hours': row['operating_hours'],
                    'autismSpecialist': bool(row['autism_specialist']),
                    'ldSpecialist': bool(row['ld_specialist']),
                    'crisisSupport': bool(row['crisis_support']),
                })

            # Log blocked decision
            AuditLogger.log_decision(
                conn, params['age'], params['diagnosis'], params,
                'ADMISSION_BLOCKED',
                reasoning={'cetr_reasons': policy['reasons']}
            )

        elif policy['risk_level'] == 'MEDIUM':
            alternatives = [{
                'name': 'Assessment recommended',
                'type': 'Clinical Review',
                'availability': 'Schedule with MDT'
            }]

            AuditLogger.log_decision(
                conn, params['age'], params['diagnosis'], params,
                'REVIEW_REQUIRED',
                reasoning={'cetr_reasons': policy['reasons']}
            )

        else:
            # Step 2b: MCDA hospital scoring for approved admissions
            q = '''SELECT * FROM hospitals
                   WHERE cqc_rating IN ('Good','Outstanding')
                   AND available_beds > 0'''
            q_params = []
            if params['age'] < 16:
                q += ' AND age_min <= ?'
                q_params.append(params['age'])
            if params.get('gender') in ['Male', 'Female']:
                q += " AND gender_restriction IN ('Mixed', ?)"
                q_params.append(f"{params['gender']} Only")
                
            if params['location']:
                q += ' AND location LIKE ?'
                q_params.append(f"%{params['location']}%")

            for row in conn.execute(q, q_params).fetchall():
                score, breakdown, dist = MCDAEngine.score_hospital(
                    row, params['latitude'], params['longitude']
                )
                suitable_hospitals.append({
                    'name': row['name'],
                    'location': row['location'],
                    'totalBeds': row['total_beds'],
                    'availableBeds': row['available_beds'],
                    'cqcRating': row['cqc_rating'],
                    'autismAccredited': bool(row['autism_accredited']),
                    'ldSpecialist': bool(row['ld_specialist_ward']),
                    'hasSALT': bool(row['has_salt']),
                    'hasSensoryRoom': bool(row['has_sensory_room']),
                    'hasOT': bool(row['has_ot']),
                    'suitabilityScore': score,
                    'scoreBreakdown': breakdown,
                    'distance': round(dist, 1) if dist < 999 else None,
                })

            # Sort by MCDA suitability score (highest first)
            suitable_hospitals.sort(
                key=lambda x: x['suitabilityScore'], reverse=True
            )
            suitable_hospitals = suitable_hospitals[:5]

            # Log approved decision
            top_match = suitable_hospitals[0] if suitable_hospitals else None
            AuditLogger.log_decision(
                conn, params['age'], params['diagnosis'], params,
                'ADMISSION_APPROVED',
                mcda_score=top_match['suitabilityScore'] if top_match else None,
                facility_name=top_match['name'] if top_match else None,
                reasoning={
                    'matched_count': len(suitable_hospitals),
                    'top_breakdown': top_match['scoreBreakdown'] if top_match else {}
                }
            )

    finally:
        conn.close()

    return jsonify({
        'avoidanceAlert': policy['avoidance_alert'],
        'riskLevel': policy['risk_level'],
        'reasons': policy['reasons'],
        'recommendation': policy['recommendation'],
        'sensoryFlag': policy.get('sensory_flag', False),
        'alternatives': alternatives,
        'suitableHospitals': suitable_hospitals,
        'timestamp': datetime.now().isoformat(),
        'cetrCompliant': True
    })


# ─── API: COMMUNITY SERVICES ─────────────────────
@app.route('/api/community_services', methods=['GET'])
@api_error_handler
def community_services():
    location = request.args.get('location', '')
    age = request.args.get('age', 15)
    autism = request.args.get('autism', 'false') == 'true'
    crisis = request.args.get('crisis', 'false') == 'true'

    conn = get_db()
    try:
        q = ('SELECT * FROM community_services '
             'WHERE available = 1 AND age_min <= ? AND age_max >= ?')
        params = [age, age]

        if location:
            safe_loc = location.replace('%', '\\%').replace('_', '\\_')
            q += " AND location LIKE ? ESCAPE '\\'"
            params.append(f'%{safe_loc}%')
        if autism:
            q += ' AND autism_specialist = 1'
        if crisis:
            q += ' AND crisis_support = 1'

        q += ' ORDER BY crisis_support DESC, (capacity - current_load) DESC LIMIT 20'

        rows = conn.execute(q, params).fetchall()
        services = []
        for row in rows:
            services.append({
                'name': row['name'],
                'type': row['service_type'],
                'location': row['location'],
                'available': bool(row['available']),
                'capacity': row['capacity'],
                'currentLoad': row['current_load'],
                'spacesAvailable': row['capacity'] - row['current_load'],
                'autismSpecialist': bool(row['autism_specialist']),
                'ldSpecialist': bool(row['ld_specialist']),
                'crisisSupport': bool(row['crisis_support']),
                'respiteCare': bool(row['respite_care']),
                'contact': row['contact_number'],
                'hours': row['operating_hours'],
            })
        return jsonify(services)
    finally:
        conn.close()


# ─── API: MAP DATA ────────────────────────────────
@app.route('/api/map_data', methods=['GET'])
@api_error_handler
def map_data():
    """Return GPS coordinates for Leaflet map visualisation."""
    conn = get_db()
    try:
        hospitals = conn.execute(
            'SELECT name, location, latitude, longitude, cqc_rating, '
            'available_beds, autism_accredited FROM hospitals'
        ).fetchall()
        community = conn.execute(
            'SELECT name, location, latitude, longitude, service_type, '
            'crisis_support FROM community_services WHERE available = 1'
        ).fetchall()

        return jsonify({
            'hospitals': [dict(h) for h in hospitals],
            'communityServices': [dict(c) for c in community]
        })
    finally:
        conn.close()


# ─── API: AUDIT LOG ──────────────────────────────
@app.route('/api/audit_log', methods=['GET'])
@api_error_handler
def audit_log():
    """Return the decision audit trail for clinical accountability."""
    limit = min(int(request.args.get('limit', 50)), 200)
    conn = get_db()
    try:
        rows = conn.execute(
            'SELECT * FROM decision_audit_log ORDER BY timestamp DESC LIMIT ?',
            (limit,)
        ).fetchall()

        return jsonify({
            'count': len(rows),
            'decisions': [dict(r) for r in rows],
            'timestamp': datetime.now().isoformat()
        })
    finally:
        conn.close()

# ─── API: JUSTIFICATION EXPORTER (Clinical Audacity) ─

class JustificationPDF(FPDF):
    def header(self):
        self.set_fill_color(0, 94, 184) # NHS Blue
        self.rect(0, 0, 210, 20, 'F')
        self.set_text_color(255, 255, 255)
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'HAAS: Clinical Referral Justification', 0, 1, 'C')
        self.set_text_color(0, 0, 0)
        self.ln(10)

    def chapter_title(self, label):
        self.set_font('Arial', 'B', 12)
        self.set_fill_color(230, 230, 230)
        self.cell(0, 10, label, 0, 1, 'L', 1)
        self.ln(4)

    def chapter_body(self, body):
        self.set_font('Arial', '', 11)
        self.multi_cell(0, 8, body)
        self.ln()

@app.route('/api/export_justification', methods=['POST'])
@api_error_handler
def export_justification():
    """Generates a professional PDF clinical justification for a decision."""
    data = request.json
    patient_id = data.get('patientId', 'ANON-' + hashlib.sha256(str(datetime.now()).encode()).hexdigest()[:6])
    decision = data.get('decision', 'ADMISSION_BLOCKED')
    reasoning = data.get('reasoning', "Criteria for involuntary detention not met under CETR §4.2 guidelines.")
    hospital_name = data.get('hospitalName', 'Community Treatment Alternative')
    
    pdf = JustificationPDF()
    pdf.add_page()
    
    pdf.chapter_title(f"Decision: {decision}")
    pdf.chapter_body(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nPatient Identifier: {patient_id}\nAuthorising System: HAAS (Policy Enforcement Mode)")
    
    pdf.chapter_title("Clinical Rationale & Evidence")
    pdf.chapter_body(reasoning)
    
    if decision == 'ADMISSION_APPROVED':
        pdf.chapter_title("Priority Matching Information")
        pdf.chapter_body(f"The system has identified the most suitable clinical placement based on MCDA quality metrics (CQC, Specialism, Environment).\n\nMatched Facility: {hospital_name}")
    else:
        pdf.chapter_title("Admission Avoidance Strategy")
        pdf.chapter_body("In accordance with the 'Transforming Care' agenda, an admission has been avoided. The clinician is advised to utilise the Community Crisis Team and Intensive Support Team (IST) provided in the alternative match list.")
    
    pdf.set_y(-30)
    pdf.set_font('Arial', 'I', 8)
    pdf.cell(0, 10, 'Signed: HAAS Digital Clinical Gatekeeper | NHS England Protocol §4.2', 0, 1, 'C')

    pdf_output = pdf.output(dest='S')
    return send_file(
        io.BytesIO(pdf_output),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"HAAS_Justification_{patient_id[:8]}.pdf"
    )

# ════════════════════════════════════════════════════
# APPLICATION ENTRY POINT
# ════════════════════════════════════════════════════
if __name__ == '__main__':
    ensure_database()
    print('=' * 70)
    print('  [HAAS] Hospital Admission Avoidance System')
    print('  PDF Exports & Audit Trails Ready')
    print('  Interactive Tutorial: Enabled')
    print('=' * 70)
    app.run(debug=True, port=5000)
