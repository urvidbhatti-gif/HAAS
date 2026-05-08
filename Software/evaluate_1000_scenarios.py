"""
Hospital Admission Avoidance System (HAAS) – 1,000 Scenario Evaluation Engine
CN7000 MSc Dissertation – University of East London
Author: Urvi Bhatti | Supervisor: Dr. Rasha Hafidh

This script generates and evaluates N=1,000 synthetic clinical crisis
scenarios against the HAAS deterministic CETR engine and MCDA matcher,
producing the empirical metrics cited in Chapter 4:
  - Admission Avoidance Rate (AAR)
  - Qualitative Match Accuracy (QMA)
  - Baseline comparison (proximity-only model)

References:
  - Braun & Clarke (2006): Thematic analysis for scenario profiles
  - Ishizaka & Nemery (2013): MCDA evaluation methodology
  - NHS England (2023): CETR statutory guidelines
"""
import sqlite3
import random
import os
import math
import json
from datetime import datetime

# ────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
N_SCENARIOS = 1000

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'hospitals.db')

# MCDA Weights (aligned with dissertation §2.1.10)
W_CQC = 0.45
W_SPECIALIST = 0.35
W_PROXIMITY = 0.20

# ────────────────────────────────────────────────────
# CETR Keywords (matching CETRPolicyEngine in app.py)
# ────────────────────────────────────────────────────
ASD_LD_KEYWORDS = {'autism', 'asd', 'ld', 'learning_disability'}

# Diagnosis distribution based on published NHS data
DIAGNOSES = [
    ('autism', 0.30),
    ('learning_disability', 0.20),
    ('asd_ld_comorbid', 0.10),
    ('depression', 0.12),
    ('schizophrenia', 0.08),
    ('bipolar', 0.07),
    ('anxiety', 0.06),
    ('ptsd', 0.04),
    ('personality_disorder', 0.03),
]

CITIES = [
    ("London",       51.5074, -0.1278,  0.25),
    ("Manchester",   53.4808, -2.2426,  0.12),
    ("Birmingham",   52.4862, -1.8904,  0.10),
    ("Leeds",        53.8008, -1.5491,  0.08),
    ("Liverpool",    53.4084, -2.9916,  0.07),
    ("Bristol",      51.4545, -2.5879,  0.07),
    ("Newcastle",    54.9783, -1.6178,  0.06),
    ("Sheffield",    53.3811, -1.4701,  0.06),
    ("Nottingham",   52.9548, -1.1581,  0.05),
    ("Southampton",  50.9097, -1.4044,  0.04),
    ("Rural_Isolated", 52.0, -3.0,     0.10),  # Service desert simulation
]


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate great-circle distance between two points in km."""
    R = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def generate_scenario(idx):
    """Generate a single synthetic patient crisis scenario."""
    # Select diagnosis
    diag_names = [d[0] for d in DIAGNOSES]
    diag_weights = [d[1] for d in DIAGNOSES]
    diagnosis = random.choices(diag_names, weights=diag_weights, k=1)[0]

    is_asd_ld = any(kw in diagnosis for kw in ASD_LD_KEYWORDS)

    # Age distribution: skewed younger for ASD/LD
    if is_asd_ld:
        age = random.choices(range(8, 55), weights=[3 if a < 18 else 1 for a in range(8, 55)], k=1)[0]
    else:
        age = random.randint(16, 65)

    # Mental illness: ASD/LD patients less likely to have treatable MI
    if is_asd_ld:
        has_mental_illness = random.random() < 0.35
    else:
        has_mental_illness = random.random() < 0.85

    # Location
    city_names = [c[0] for c in CITIES]
    city_weights = [c[3] for c in CITIES]
    city = random.choices(city_names, weights=city_weights, k=1)[0]
    city_data = next(c for c in CITIES if c[0] == city)
    lat = city_data[1] + random.gauss(0, 0.15)
    lon = city_data[2] + random.gauss(0, 0.15)

    # Sensory trigger: more common in ASD
    sensory_trigger = is_asd_ld and random.random() < 0.40

    # Community support exhausted
    community_exhausted = random.random() < 0.60

    return {
        'id': idx,
        'age': age,
        'diagnosis': diagnosis,
        'has_mental_illness': has_mental_illness,
        'is_asd_ld': is_asd_ld,
        'location': city,
        'latitude': lat,
        'longitude': lon,
        'sensory_trigger': sensory_trigger,
        'community_exhausted': community_exhausted,
    }


def cetr_evaluate(scenario):
    """Apply CETR deterministic gatekeeping rules."""
    is_asd_ld = scenario['is_asd_ld']
    has_mi = scenario['has_mental_illness']
    age = scenario['age']
    sensory = scenario['sensory_trigger']

    avoidance_alert = False
    reasons = []
    risk_level = 'LOW'
    sensory_flag = False

    # Sensory Meltdown Flag
    if is_asd_ld and sensory:
        sensory_flag = True
        reasons.append('SENSORY MELTDOWN FLAG: Environmental crisis suspected')

    # Core CETR Logic
    if is_asd_ld and not has_mi:
        avoidance_alert = True
        risk_level = 'HIGH'
        reasons.append(f'ASD/LD patient (age {age}) without treatable MI — CETR §4.2 BLOCK')
    elif is_asd_ld and has_mi and not scenario['community_exhausted']:
        risk_level = 'MEDIUM'
        reasons.append('ASD/LD with MI but community not exhausted — REVIEW')

    return {
        'avoidance_alert': avoidance_alert,
        'risk_level': risk_level,
        'reasons': reasons,
        'sensory_flag': sensory_flag,
    }


def mcda_score_hospital(hospital, patient_lat, patient_lon):
    """Calculate IMS using the 3-pillar WSM."""
    # Pillar 1: CQC (max 45)
    cqc_map = {'Outstanding': 45, 'Good': 30, 'Requires Improvement': 10, 'Inadequate': 0}
    cqc_score = cqc_map.get(hospital['cqc_rating'], 0)

    # Pillar 2: Specialist (max 35)
    spec = 0
    if hospital['autism_accredited']:
        spec += 15
    if hospital['ld_specialist_ward']:
        spec += 10
    services = sum([hospital.get('has_salt', 0), hospital.get('has_sensory_room', 0),
                    hospital.get('has_ot', 0), hospital.get('has_psychology', 0)])
    spec += min(int(services * 2.5), 10)
    spec = min(spec, 35)

    # Pillar 3: Proximity (max 20)
    dist = haversine_distance(patient_lat, patient_lon, hospital['latitude'], hospital['longitude'])
    if dist < 10:
        prox = 20
    elif dist < 25:
        prox = 15
    elif dist < 50:
        prox = 10
    elif dist < 100:
        prox = 5
    else:
        prox = 0

    return cqc_score + spec + prox, dist


def baseline_proximity_only(hospitals, patient_lat, patient_lon):
    """Baseline model: nearest bed wins (no gatekeeping, no quality check)."""
    scored = []
    for h in hospitals:
        if h['available_beds'] > 0:
            dist = haversine_distance(patient_lat, patient_lon, h['latitude'], h['longitude'])
            scored.append((h, dist))
    scored.sort(key=lambda x: x[1])
    return scored[0] if scored else (None, 999)


def run_evaluation():
    """Execute the full 1,000-scenario evaluation."""
    print('=' * 70)
    print('  HAAS 1,000-Scenario Evaluation Engine')
    print(f'  Timestamp: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'  Random Seed: {SEED}')
    print('=' * 70)

    # Load hospitals from database
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    hospitals_raw = conn.execute('SELECT * FROM hospitals').fetchall()
    hospitals = [dict(h) for h in hospitals_raw]
    conn.close()

    print(f'\n  Database: {len(hospitals)} hospitals loaded')
    print(f'  Generating {N_SCENARIOS} synthetic crisis scenarios...\n')

    # Generate scenarios
    scenarios = [generate_scenario(i) for i in range(N_SCENARIOS)]

    # Counters
    haas_blocked = 0
    haas_approved = 0
    haas_review = 0
    sensory_flags = 0
    baseline_total = 0

    # Quality metrics
    haas_good_matches = 0
    haas_total_matches = 0
    baseline_good_matches = 0
    baseline_total_matches = 0

    results = []

    for scenario in scenarios:
        # HAAS evaluation
        cetr_result = cetr_evaluate(scenario)

        if cetr_result['sensory_flag']:
            sensory_flags += 1

        if cetr_result['avoidance_alert']:
            haas_blocked += 1
            results.append({**scenario, 'haas_decision': 'BLOCKED', 'haas_score': None})
        else:
            # MCDA matching for approved/review cases
            eligible = [h for h in hospitals
                        if h['available_beds'] > 0
                        and h['cqc_rating'] in ('Good', 'Outstanding')]

            if scenario['age'] < 16:
                eligible = [h for h in eligible if h['age_min'] <= scenario['age']]

            if eligible:
                scored = [(h, *mcda_score_hospital(h, scenario['latitude'], scenario['longitude']))
                          for h in eligible]
                scored.sort(key=lambda x: x[1], reverse=True)
                best = scored[0]
                haas_approved += 1
                haas_total_matches += 1
                if best[0]['cqc_rating'] in ('Good', 'Outstanding'):
                    haas_good_matches += 1
                results.append({
                    **scenario,
                    'haas_decision': 'APPROVED',
                    'haas_score': best[1],
                    'haas_hospital': best[0]['name'],
                    'haas_cqc': best[0]['cqc_rating'],
                    'haas_distance': round(best[2], 1),
                })
            else:
                haas_review += 1
                results.append({**scenario, 'haas_decision': 'NO_MATCH', 'haas_score': None})

        # Baseline evaluation (proximity only, no gatekeeping)
        baseline_match, baseline_dist = baseline_proximity_only(
            hospitals, scenario['latitude'], scenario['longitude']
        )
        baseline_total += 1
        if baseline_match:
            baseline_total_matches += 1
            if baseline_match['cqc_rating'] in ('Good', 'Outstanding'):
                baseline_good_matches += 1

    # ────────────────────────────────────────────────
    # Results Summary
    # ────────────────────────────────────────────────
    aar = (haas_blocked / N_SCENARIOS) * 100
    qma_haas = (haas_good_matches / haas_total_matches * 100) if haas_total_matches > 0 else 0
    qma_baseline = (baseline_good_matches / baseline_total_matches * 100) if baseline_total_matches > 0 else 0
    qma_improvement = ((qma_haas - qma_baseline) / qma_baseline * 100) if qma_baseline > 0 else 0

    print('┌' + '─' * 68 + '┐')
    print('│ {:^66s} │'.format('HAAS EVALUATION RESULTS'))
    print('├' + '─' * 68 + '┤')
    print(f'│ Total Scenarios Evaluated:           {N_SCENARIOS:>6d}{" " * 26}│')
    print(f'│ Admissions BLOCKED (CETR):           {haas_blocked:>6d}  ({aar:.1f}%){" " * 17}│')
    print(f'│ Admissions APPROVED (MCDA):          {haas_approved:>6d}  ({haas_approved/N_SCENARIOS*100:.1f}%){" " * 17}│')
    print(f'│ Sensory Meltdown Flags:              {sensory_flags:>6d}{" " * 26}│')
    print('├' + '─' * 68 + '┤')
    print(f'│ HAAS Qualitative Match Accuracy:     {qma_haas:>6.1f}%{" " * 25}│')
    print(f'│ Baseline QMA (proximity-only):       {qma_baseline:>6.1f}%{" " * 25}│')
    print(f'│ HAAS Improvement over Baseline:      {qma_improvement:>6.1f}%{" " * 25}│')
    print('└' + '─' * 68 + '┘')

    # Diagnosis breakdown
    print('\n  Admission Avoidance by Diagnosis:')
    diag_blocks = {}
    for r in results:
        d = r['diagnosis']
        if d not in diag_blocks:
            diag_blocks[d] = {'total': 0, 'blocked': 0}
        diag_blocks[d]['total'] += 1
        if r['haas_decision'] == 'BLOCKED':
            diag_blocks[d]['blocked'] += 1

    for d, v in sorted(diag_blocks.items(), key=lambda x: x[1]['blocked'], reverse=True):
        pct = (v['blocked'] / v['total'] * 100) if v['total'] > 0 else 0
        bar = '█' * int(pct / 2) + '░' * (50 - int(pct / 2))
        print(f'    {d:25s} {bar} {pct:5.1f}% ({v["blocked"]}/{v["total"]})')

    # Save results to JSON
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'data', 'evaluation_results.json')
    with open(output_path, 'w') as f:
        json.dump({
            'metadata': {
                'timestamp': datetime.now().isoformat(),
                'seed': SEED,
                'n_scenarios': N_SCENARIOS,
                'db_hospitals': len(hospitals),
            },
            'summary': {
                'admission_avoidance_rate': round(aar, 1),
                'haas_qualitative_match_accuracy': round(qma_haas, 1),
                'baseline_qualitative_match_accuracy': round(qma_baseline, 1),
                'improvement_over_baseline': round(qma_improvement, 1),
                'sensory_flags_triggered': sensory_flags,
                'total_blocked': haas_blocked,
                'total_approved': haas_approved,
            },
            'diagnosis_breakdown': diag_blocks,
        }, f, indent=2, default=str)

    print(f'\n  Results exported to: {output_path}')
    print('=' * 70)

    return aar, qma_haas


if __name__ == '__main__':
    run_evaluation()
