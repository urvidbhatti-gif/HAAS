"""
Hospital Admission Avoidance System (HAAS) – Synthetic Data Generator
CN7000 MSc Dissertation – University of East London
Author: Urvi Bhatti | Supervisor: Dr. Rasha Hafidh
"""
import sqlite3
import random
import os
import math

# ────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'hospitals.db')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

CITIES = [
    ("London",       51.5074, -0.1278,  0.25, 0.15),
    ("Manchester",   53.4808, -2.2426,  0.10, 0.08),
    ("Birmingham",   52.4862, -1.8904,  0.10, 0.08),
    ("Leeds",        53.8008, -1.5491,  0.07, 0.06),
    ("Liverpool",    53.4084, -2.9916,  0.06, 0.05),
    ("Bristol",      51.4545, -2.5879,  0.06, 0.05),
    ("Newcastle",    54.9783, -1.6178,  0.05, 0.05),
    ("Sheffield",    53.3811, -1.4701,  0.05, 0.04),
    ("Nottingham",   52.9548, -1.1581,  0.05, 0.04),
    ("Southampton",  50.9097, -1.4044,  0.04, 0.04),
]

city_names = [c[0] for c in CITIES]
city_weights = [c[3] for c in CITIES]
city_coords = {c[0]: (c[1], c[2]) for c in CITIES}
city_std = {c[0]: c[4] for c in CITIES}

def gaussian_offset(city_name):
    std = city_std[city_name]
    lat_offset = random.gauss(0, std)
    lon_offset = random.gauss(0, std)
    base_lat, base_lon = city_coords[city_name]
    return (base_lat + lat_offset, base_lon + lon_offset)

c.executescript('''
CREATE TABLE hospitals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    location TEXT NOT NULL,
    total_beds INTEGER NOT NULL,
    available_beds INTEGER NOT NULL,
    specialist_beds_autism INTEGER DEFAULT 0,
    age_min INTEGER NOT NULL,
    age_max INTEGER NOT NULL,
    gender_restriction TEXT DEFAULT 'Mixed',
    has_salt BOOLEAN DEFAULT 0,
    has_sensory_room BOOLEAN DEFAULT 0,
    has_ot BOOLEAN DEFAULT 0,
    has_psychology BOOLEAN DEFAULT 0,
    has_family_therapy BOOLEAN DEFAULT 0,
    autism_accredited BOOLEAN DEFAULT 0,
    ld_specialist_ward BOOLEAN DEFAULT 0,
    cqc_rating TEXT NOT NULL,
    last_inspection_date TEXT,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL
);

CREATE TABLE community_services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    service_type TEXT NOT NULL,
    location TEXT NOT NULL,
    available BOOLEAN DEFAULT 1,
    capacity INTEGER DEFAULT 10,
    current_load INTEGER DEFAULT 0,
    age_min INTEGER DEFAULT 0,
    age_max INTEGER DEFAULT 65,
    gender_restriction TEXT DEFAULT 'Mixed',
    contact_number TEXT,
    operating_hours TEXT,
    autism_specialist BOOLEAN DEFAULT 0,
    ld_specialist BOOLEAN DEFAULT 0,
    crisis_support BOOLEAN DEFAULT 0,
    respite_care BOOLEAN DEFAULT 0,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL
);

CREATE TABLE decision_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    patient_hash TEXT NOT NULL,
    patient_age INTEGER,
    diagnosis TEXT,
    input_parameters_json TEXT,
    decision_type TEXT NOT NULL,
    mcda_suitability_score REAL,
    matched_facility_id INTEGER,
    matched_facility_name TEXT,
    reasoning_json TEXT
);
''')

# Hospitals
REALISTIC_HOSPITALS = [
    "The Spinney Intensive Care Ward", "Kemple View Specialist Autism Facility", 
    "Maudsley Hospital - High Dependency Unit", "Rampton Secure Hospital (National Hub)",
    "Elysium Healthcare - The Limes", "Avon and Wiltshire NHS Trust - Bluebell Ward",
    "Tavistock and Portman - Specialist ASD Services", "Cygnet Hospital Bury - Hudson Ward",
    "Priory Hospital Cheadle Royal - CAMHS", "St Andrew's Healthcare - FitzRoy House",
    "Greater Manchester Mental Health - The Curve", "South London and Maudsley - Bethlem Royal",
    "Lancashire & South Cumbria - Guild Lodge", "Southern Health - Antelope House",
    "Oxford Health NHS - Littlemore Centre", "Northumberland, Tyne and Wear - Ferndene",
    "Sussex Partnership - Mill View Hospital", "Derbyshire Healthcare - Radbourne Unit",
    "Surrey and Borders - Farnham Road Hospital", "Kent and Medway - Trevor Gibbens Unit",
    "Devon Partnership - Langdon Hospital", "Somerset NHS Foundation - Rydon Ward",
    "Tees, Esk and Wear Valleys - Roseberry Park", "Mersey Care NHS - Ashworth Hospital",
    "Cheshire and Wirral - Bowmere Hospital", "Norfolk and Suffolk - Hellesdon Hospital"
]
ods_prefixes = {"London": "RLR", "Manchester": "R0A", "Birmingham": "RRK", "Leeds": "RRP", "Bristol": "RA7", "Newcastle": "RTV", "Sheffield": "RHQ", "Nottingham": "RWH", "Southampton": "RHM"}
ratings = ["Outstanding", "Good", "Requires Improvement", "Inadequate"]

for i in range(220):
    loc_name = random.choices(city_names, weights=city_weights, k=1)[0]
    base_name = random.choice(REALISTIC_HOSPITALS)
    ods_code = f"{ods_prefixes.get(loc_name, 'RXX')}{100 + i}"
    # Sometimes append a location to the base name if it doesn't have one
    name = f"{base_name} ({loc_name}) [{ods_code}]"
    
    total = random.randint(15, 60)
    avail = random.randint(1, total // 3)
    spec = random.randint(1, max(2, total // 4))
    age_min = random.choice([12, 16, 18])
    age_max = 65 if age_min >= 18 else age_min + 6
    lat, lon = gaussian_offset(loc_name)
    gender_restriction = random.choices(['Mixed', 'Male Only', 'Female Only'], weights=[0.7, 0.15, 0.15], k=1)[0]
    
    c.execute('INSERT INTO hospitals (name, location, total_beds, available_beds, specialist_beds_autism, age_min, age_max, gender_restriction, has_salt, has_sensory_room, has_ot, has_psychology, autism_accredited, ld_specialist_ward, cqc_rating, last_inspection_date, latitude, longitude) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
               (name, loc_name, total, avail, spec, age_min, age_max, gender_restriction, random.randint(0,1), random.randint(0,1), random.randint(0,1), random.randint(0,1), random.randint(0,1), random.randint(0,1), random.choice(ratings), f"2024-{random.randint(1,12):02d}", lat, lon))

# Community Services
REALISTIC_COMMUNITY = [
    "Learning Disabilities Intensive Support Team (IST)", "Community Crisis House",
    "Assertive Outreach Team", "Autism Diagnostic Service (LADS)", 
    "Forward Thinking - Youth Crisis Team", "Steps to Wellbeing",
    "Integrated Community Autism Team", "Crisis Resolution Home Treatment",
    "Early Intervention in Psychosis Service", "Specialist Perinatal Mental Health",
    "Community Recovery Service", "Rapid Response Outreach Team"
]

for i in range(150):
    loc_name = random.choices(city_names, weights=city_weights, k=1)[0]
    stype = random.choice(REALISTIC_COMMUNITY)
    # E.g. "Manchester Assertive Outreach Team"
    name = f"{loc_name} {stype}"
    lat, lon = gaussian_offset(loc_name)
    gender_restriction = random.choices(['Mixed', 'Male Only', 'Female Only'], weights=[0.8, 0.1, 0.1], k=1)[0]
    
    c.execute('INSERT INTO community_services (name, service_type, location, available, capacity, current_load, age_min, age_max, gender_restriction, contact_number, operating_hours, autism_specialist, ld_specialist, crisis_support, respite_care, latitude, longitude) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
              (name, stype, loc_name, 1, 20, random.randint(0, 15), 12, 65, gender_restriction, f"0800-{random.randint(100,999)}", "24/7", 1, 1, 1 if "Crisis" in stype else 0, 1 if "Respite" in stype else 0, lat, lon))

conn.commit()
conn.close()
print("Database generated successfully.")
