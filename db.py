"""Database layer: creates the tables and fills them with SAMPLE data.

IMPORTANT: the records created by seed_database() are SAMPLE (test) data made
by the project group so the system can be demonstrated and tested. They are
not real IPAM student records.
"""
import random
import sqlite3
from werkzeug.security import generate_password_hash
import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS campuses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    location TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS programmes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    programme_id INTEGER NOT NULL REFERENCES programmes(id),
    stage INTEGER NOT NULL            -- 1..4 = Year1 Sem1, Year1 Sem2, Year2 Sem1, Year2 Sem2
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('sysadmin','management','coordinator','lecturer','student')),
    campus_id INTEGER REFERENCES campuses(id),
    student_id INTEGER REFERENCES students(id),
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reg_no TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    gender TEXT NOT NULL,
    phone TEXT,
    campus_id INTEGER NOT NULL REFERENCES campuses(id),
    programme_id INTEGER NOT NULL REFERENCES programmes(id),
    intake_year INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'Active'
);
CREATE TABLE IF NOT EXISTS allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id),
    campus_id INTEGER NOT NULL REFERENCES campuses(id),
    lecturer_id INTEGER NOT NULL REFERENCES users(id),
    term TEXT NOT NULL,
    UNIQUE (course_id, campus_id, term)
);
CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    course_id INTEGER NOT NULL REFERENCES courses(id),
    term TEXT NOT NULL,
    ca_score REAL,
    exam_score REAL,
    attendance REAL,
    UNIQUE (student_id, course_id, term)
);
CREATE TABLE IF NOT EXISTS enrolment_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campus_id INTEGER NOT NULL REFERENCES campuses(id),
    programme_id INTEGER NOT NULL REFERENCES programmes(id),
    year INTEGER NOT NULL,
    intake INTEGER NOT NULL,
    UNIQUE (campus_id, programme_id, year)
);
CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    campus_id INTEGER REFERENCES campuses(id),   -- NULL = all campuses
    posted_by INTEGER NOT NULL REFERENCES users(id),
    posted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    detail TEXT,
    at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CAMPUSES = [
    ("Freetown Campus", "Tower Hill, Freetown"),
    ("Bo Campus", "Bo City, Southern Province"),
    ("Kenema Campus", "Kenema City, Eastern Province"),
    ("Makeni Campus", "Makeni City, Northern Province"),
]
PROGRAMMES = [
    ("DPA", "Diploma in Public Administration"),
    ("DBM", "Diploma in Business Management"),
    ("DAF", "Diploma in Accounting and Finance"),
    ("DHR", "Diploma in Human Resource Management"),
]
COURSE_TITLES = {
    "DPA": ["Introduction to Public Administration", "Principles of Management", "Communication Skills", "Introduction to Computing",
            "Public Policy Analysis", "Local Government Administration", "Administrative Law", "Research Methods",
            "Public Financial Management", "Development Administration", "Ethics and Accountability", "Project Planning",
            "Public Sector Reform", "Governance and Democracy", "Records Management", "Project Report"],
    "DBM": ["Introduction to Business", "Principles of Management", "Business Communication", "Introduction to Computing",
            "Marketing Principles", "Business Mathematics", "Business Law", "Entrepreneurship",
            "Operations Management", "Organisational Behaviour", "Business Ethics", "Small Business Finance",
            "Strategic Management", "Customer Relations", "Business Statistics", "Business Project"],
    "DAF": ["Principles of Accounting", "Business Mathematics", "Economics I", "Introduction to Computing",
            "Financial Accounting", "Cost Accounting", "Economics II", "Commercial Law",
            "Taxation", "Auditing Principles", "Public Finance", "Management Accounting",
            "Financial Management", "Accounting Software", "Banking and Finance", "Accounting Project"],
    "DHR": ["Introduction to HR Management", "Principles of Management", "Communication Skills", "Introduction to Computing",
            "Recruitment and Selection", "Employment Law", "Organisational Behaviour", "Research Methods",
            "Training and Development", "Industrial Relations", "Performance Management", "Compensation Management",
            "Strategic HRM", "Labour Economics", "HR Information Systems", "HR Project"],
}
TERMS = ["2025/2026 Semester 1", "2025/2026 Semester 2", "2026/2027 Semester 1"]

# Intake (new students) per campus. Years 2020-2024 are history only;
# 2025 and 2026 are the cohorts that exist as student records.
HISTORY = {
    "Freetown Campus": {2020: 18, 2021: 21, 2022: 23, 2023: 26, 2024: 28},
    "Bo Campus":       {2020: 17, 2021: 18, 2022: 18, 2023: 19, 2024: 20},
    "Kenema Campus":   {2020: 16, 2021: 17, 2022: 18, 2023: 19, 2024: 19},
    "Makeni Campus":   {2020: 15, 2021: 17, 2022: 19, 2023: 20, 2024: 19},
}
COHORTS = {  # campus -> {intake_year: number of students}
    "Freetown Campus": {2025: 30, 2026: 34},
    "Bo Campus":       {2025: 19, 2026: 19},
    "Kenema Campus":   {2025: 18, 2026: 14},
    "Makeni Campus":   {2025: 17, 2026: 9},
}

MALE_FIRST = ["Mohamed", "Abdul", "Ibrahim", "Alusine", "Sorie", "Foday", "Joseph", "Santigie", "Abu", "Idrissa", "Emmanuel",
              "Sahr", "Alpha", "Musa", "Osman", "Thomas", "Samuel", "Patrick", "Bockarie", "Kelfala", "Lansana", "Ishmael"]
FEMALE_FIRST = ["Fatmata", "Aminata", "Isatu", "Mariama", "Hawa", "Kadiatu", "Mabinty", "Zainab", "Adama", "Memunatu", "Marie",
                "Yeabu", "Saffiatu", "Hannah", "Rugiatu", "Nenneh", "Jariatu", "Haja", "Fanta", "Salamatu"]
SURNAMES = ["Kamara", "Koroma", "Bangura", "Conteh", "Sesay", "Turay", "Mansaray", "Kallon", "Sankoh", "Jalloh", "Barrie", "Fofanah",
            "Kargbo", "Samura", "Lahai", "Mboma", "Kanu", "Bockarie", "Dumbuya", "Sillah", "Gbla", "Tucker", "Momoh", "Massaquoi",
            "Vandi", "Kabba", "Wurie", "Songo", "Kpaka", "Swaray"]

LECTURERS = {  # campus -> [(username, full name)]
    "Freetown Campus": [("samuel.gbani", "Samuel Sundima Gbani"), ("mohamed.turay", "Mohamed Lamin Turay"), ("joseph.kallon", "Joseph Kallon")],
    "Bo Campus": [("fatmata.koroma", "Fatmata Koroma"), ("hawa.mansaray", "Hawa Mansaray")],
    "Kenema Campus": [("alusine.conteh", "Alusine Conteh"), ("mabinty.sesay", "Mabinty Sesay")],
    "Makeni Campus": [("isatu.bangura", "Isatu Bangura"), ("foday.kargbo", "Foday Kargbo")],
}
COORDINATORS = {
    "Freetown Campus": ("michael.sillah", "Michael Sillah"),
    "Bo Campus": ("sahr.bangallie", "Sahr Bangallie"),
    "Kenema Campus": ("aminata.fofanah", "Aminata Fofanah"),
    "Makeni Campus": ("santigie.samura", "Santigie Samura"),
}


def get_db():
    conn = sqlite3.connect(config.DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def _split(total, shares):
    """Split a total into whole numbers following the shares (largest remainder)."""
    raw = [total * s for s in shares]
    base = [int(x) for x in raw]
    rest = total - sum(base)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - base[i], reverse=True)
    for i in order[:rest]:
        base[i] += 1
    return base


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def seed_database(reset=True):
    """Create the database and fill it with sample data. Safe to run again."""
    import os
    if reset and os.path.exists(config.DATABASE):
        os.remove(config.DATABASE)
    init_db()
    rnd = random.Random(2026)
    conn = get_db()
    cur = conn.cursor()

    cur.executemany("INSERT INTO campuses(name, location) VALUES (?,?)", CAMPUSES)
    cur.executemany("INSERT INTO programmes(code, name) VALUES (?,?)", PROGRAMMES)
    campus_id = {r["name"]: r["id"] for r in cur.execute("SELECT * FROM campuses")}
    prog_id = {r["code"]: r["id"] for r in cur.execute("SELECT * FROM programmes")}
    prog_codes = list(prog_id)

    # courses: 16 per programme (4 per stage)
    for code, titles in COURSE_TITLES.items():
        for i, title in enumerate(titles):
            stage, n = i // 4 + 1, i % 4 + 1
            cur.execute("INSERT INTO courses(code,title,programme_id,stage) VALUES (?,?,?,?)",
                        (f"{code}-{stage}0{n}", title, prog_id[code], stage))

    # staff accounts
    pw = generate_password_hash(config.DEFAULT_PASSWORD)
    cur.execute("INSERT INTO users(username,password_hash,full_name,role) VALUES (?,?,?,?)",
                (config.GROUP_USERNAME, generate_password_hash(config.GROUP_PASSWORD),
                 "Mohamed Ramadan Jalloh (Group Leader)", "sysadmin"))
    cur.execute("INSERT INTO users(username,password_hash,full_name,role) VALUES (?,?,?,?)",
                ("ibrahim.kamara", pw, "Alhaji Ibrahim Kamara (Director, Extra-Mural Studies)", "management"))
    for camp, (uname, full) in COORDINATORS.items():
        cur.execute("INSERT INTO users(username,password_hash,full_name,role,campus_id) VALUES (?,?,?,?,?)",
                    (uname, pw, full, "coordinator", campus_id[camp]))
    lect_ids = {}
    for camp, people in LECTURERS.items():
        lect_ids[camp] = []
        for uname, full in people:
            cur.execute("INSERT INTO users(username,password_hash,full_name,role,campus_id) VALUES (?,?,?,?,?)",
                        (uname, pw, full, "lecturer", campus_id[camp]))
            lect_ids[camp].append(cur.lastrowid)

    # enrolment history 2020-2024 (split across programmes)
    shares = [0.35, 0.30, 0.20, 0.15]
    for camp, years in HISTORY.items():
        for year, total in years.items():
            for code, n in zip(prog_codes, _split(total, shares)):
                cur.execute("INSERT INTO enrolment_history(campus_id,programme_id,year,intake) VALUES (?,?,?,?)",
                            (campus_id[camp], prog_id[code], year, n))

    # students (sample data)
    used = set()
    seq = {}
    students = []
    for camp, cohorts in COHORTS.items():
        for year, count in cohorts.items():
            for _ in range(count):
                female = rnd.random() < 0.45
                while True:
                    name = f"{rnd.choice(FEMALE_FIRST if female else MALE_FIRST)} {rnd.choice(SURNAMES)}"
                    if name not in used:
                        used.add(name)
                        break
                prog = rnd.choices(prog_codes, weights=shares)[0]
                key = (camp, year)
                seq[key] = seq.get(key, 0) + 1
                reg = f"IPAM/EM/{camp[:2].upper()}/{year}/{seq[key]:03d}"
                phone = f"+232 {rnd.choice(['76','77','78','79','88','99'])} {rnd.randint(100000, 999999)}"
                cur.execute("INSERT INTO students(reg_no,full_name,gender,phone,campus_id,programme_id,intake_year) VALUES (?,?,?,?,?,?,?)",
                            (reg, name, "Female" if female else "Male", phone, campus_id[camp], prog_id[prog], year))
                sid = cur.lastrowid
                students.append((sid, camp, prog, year, rnd.gauss(60, 10)))
                cur.execute("INSERT INTO users(username,password_hash,full_name,role,campus_id,student_id) VALUES (?,?,?,?,?,?)",
                            (reg.lower(), pw, name, "student", campus_id[camp], sid))

    courses = {}
    for r in cur.execute("SELECT * FROM courses ORDER BY id"):
        courses.setdefault((r["programme_id"], r["stage"]), []).append(r["id"])

    # allocations and registrations per term
    def term_stage(intake, term):
        start = {"2025/2026 Semester 1": (2025, 0), "2025/2026 Semester 2": (2025, 1), "2026/2027 Semester 1": (2026, 0)}[term]
        if intake > start[0]:
            return None
        return (start[0] - intake) * 2 + start[1] + 1

    for term in TERMS:
        for camp in COHORTS:
            pool = lect_ids[camp]
            k = 0
            for (pid, stage), cids in courses.items():
                for cid in cids:
                    cur.execute("INSERT OR IGNORE INTO allocations(course_id,campus_id,lecturer_id,term) VALUES (?,?,?,?)",
                                (cid, campus_id[camp], pool[k % len(pool)], term))
                    k += 1

    ability_term = {}
    for sid, camp, prog, intake, ability in students:
        for ti, term in enumerate(TERMS):
            stage = term_stage(intake, term)
            if stage is None or stage > 4:
                continue
            current = term == config.CURRENT_TERM
            # Makeni campus has weaker current-term performance (so the early-warning alerts have something to show)
            shift = -7 if (current and camp == "Makeni Campus") else 0
            att_shift = -9 if (current and camp == "Makeni Campus") else 0
            for cid in courses[(prog_id[prog], stage)]:
                a = ability + shift + rnd.gauss(0, 4)
                ca_pct = _clip(a + rnd.gauss(0, 7), 15, 98)
                att = _clip(45 + 0.5 * ability + att_shift + rnd.gauss(0, 9), 35, 100)
                ca = round(ca_pct / 100 * config.CA_MAX, 1)
                exam = None if current else round(_clip(a + rnd.gauss(0, 9), 10, 98) / 100 * config.EXAM_MAX, 1)
                cur.execute("INSERT INTO registrations(student_id,course_id,term,ca_score,exam_score,attendance) VALUES (?,?,?,?,?,?)",
                            (sid, cid, term, ca, exam, round(att, 1)))

    now = "2026-09-28 09:00"
    cur.execute("INSERT INTO announcements(title,body,campus_id,posted_by,posted_at) VALUES (?,?,?,?,?)",
                ("Welcome to the 2026/2027 Academic Year",
                 "Registration for 2026/2027 Semester 1 is open. Check your registered courses on your portal.", None, 2, now))
    cur.execute("INSERT INTO announcements(title,body,campus_id,posted_by,posted_at) VALUES (?,?,?,?,?)",
                ("Continuous Assessment Marks Deadline",
                 "Lecturers should submit all continuous assessment marks by the end of week 8.", None, 2, "2026-10-01 10:30"))
    conn.commit()
    conn.close()
    return True


if __name__ == "__main__":
    seed_database()
    print("Database created and filled with sample data:", config.DATABASE)
