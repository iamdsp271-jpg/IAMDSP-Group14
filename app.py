"""IAMDSP - Intelligent Academic Management and Decision Support Platform.
Main web application (Flask). Run with:  python app.py
"""
import csv
import io
import os
import secrets
from datetime import datetime
from functools import wraps

from flask import (Flask, Response, abort, flash, g, redirect, render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import analytics
import charts
import config
import db

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

if not os.path.exists(config.DATABASE):
    db.seed_database()
else:
    db.init_db()

ROLE_LABELS = {"sysadmin": "System Administrator", "management": "Management", "coordinator": "Campus Coordinator",
               "lecturer": "Lecturer", "student": "Student"}


# ----------------------------------------------------------------- helpers
def conn():
    if "db" not in g:
        g.db = db.get_db()
    return g.db


@app.teardown_appcontext
def close_db(_):
    c = g.pop("db", None)
    if c is not None:
        c.close()


def log(action, detail=""):
    conn().execute("INSERT INTO audit_log(user_id, action, detail) VALUES (?,?,?)",
                   (session.get("uid"), action, detail))
    conn().commit()


@app.before_request
def load_user():
    g.user = None
    if "uid" in session:
        g.user = conn().execute("SELECT * FROM users WHERE id=? AND active=1", (session["uid"],)).fetchone()
        if g.user is None:
            session.clear()
    if request.method == "POST":
        token = session.get("csrf")
        if not token or token != request.form.get("csrf_token"):
            abort(400, "Invalid form token. Go back, refresh the page and try again.")


@app.context_processor
def inject():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return {"user": g.get("user"), "role_labels": ROLE_LABELS, "csrf_token": session["csrf"],
            "current_term": config.CURRENT_TERM, "grade": analytics.grade}


def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if g.user is None:
                return redirect(url_for("login", next=request.path))
            if roles and g.user["role"] not in roles:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


STAFF_ALL = ("sysadmin", "management")


def campus_scope():
    """campus id that this user is limited to (None = all campuses)."""
    return g.user["campus_id"] if g.user["role"] in ("coordinator", "lecturer") else None


@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code=403, message="You do not have permission to open this page."), 403


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, message="Page not found."), 404


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400, message=getattr(e, "description", "Bad request")), 400


# ----------------------------------------------------------------- login
@app.route("/", methods=["GET"])
def home():
    return redirect(url_for("dashboard") if g.user else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        uname = request.form.get("username", "").strip().lower().replace(" ", "")
        pw = request.form.get("password", "")
        row = conn().execute("SELECT * FROM users WHERE REPLACE(LOWER(username),' ','')=? AND active=1", (uname,)).fetchone()
        if row and check_password_hash(row["password_hash"], pw):
            session.clear()
            session["uid"] = row["id"]
            session["csrf"] = secrets.token_hex(16)
            g.user = row
            log("login", row["username"])
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Wrong username or password. Please try again.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ----------------------------------------------------------------- dashboards
@app.route("/dashboard")
@login_required()
def dashboard():
    role = g.user["role"]
    c = conn()
    anns = c.execute("""SELECT a.*, u.full_name AS author FROM announcements a JOIN users u ON u.id=a.posted_by
        WHERE a.campus_id IS NULL OR a.campus_id=? ORDER BY a.posted_at DESC LIMIT 5""", (g.user["campus_id"],)).fetchall()
    if role == "student":
        return redirect(url_for("my_record"))
    if role == "lecturer":
        allocs = c.execute("""SELECT al.id, c.code, c.title, ca.name AS campus,
              (SELECT COUNT(*) FROM registrations r JOIN students s ON s.id=r.student_id
                WHERE r.course_id=al.course_id AND r.term=al.term AND s.campus_id=al.campus_id) AS n
            FROM allocations al JOIN courses c ON c.id=al.course_id JOIN campuses ca ON ca.id=al.campus_id
            WHERE al.lecturer_id=? AND al.term=? ORDER BY c.code""", (g.user["id"], config.CURRENT_TERM)).fetchall()
        allocs = [a for a in allocs if a["n"] > 0]
        return render_template("dashboard_lecturer.html", allocs=allocs, anns=anns)

    scope = campus_scope()
    rows, last = analytics.campus_summary()
    if scope:
        name = c.execute("SELECT name FROM campuses WHERE id=?", (scope,)).fetchone()["name"]
        rows = [r for r in rows if r["campus"] == name]
    risk, metrics = analytics.at_risk_students(campus_id=scope)
    alerts = analytics.early_warnings()
    if scope:
        alerts = [a for a in alerts if a["campus"] == name]
    n_students = c.execute("SELECT COUNT(*) n FROM students WHERE status='Active'" + (" AND campus_id=?" if scope else ""),
                           (scope,) if scope else ()).fetchone()["n"]
    n_courses = c.execute("SELECT COUNT(DISTINCT course_id) n FROM registrations WHERE term=?", (config.CURRENT_TERM,)).fetchone()["n"]
    n_staff = c.execute("SELECT COUNT(*) n FROM users WHERE role IN ('lecturer','coordinator')" + (" AND campus_id=?" if scope else ""),
                        (scope,) if scope else ()).fetchone()["n"]
    labels = [r["campus"].replace(" Campus", "") for r in rows]
    perf = charts.bar_chart(labels, [("Average CA %", [r["cur_ca"] for r in rows]), ("Attendance %", [r["cur_att"] for r in rows])],
                            title="Current term: average CA and attendance by campus", unit="")
    trends = analytics.enrolment_trends("campus")
    if scope:
        trends = [t for t in trends if t["name"] == name]
    enr = charts.line_chart(trends[0]["years"] + [trends[0]["forecast_year"]] if trends else [],
                            [(t["name"].replace(" Campus", ""), t["values"] + [t["forecast"]]) for t in trends],
                            title="New intake per year (dashed = forecast)", forecast_from=len(trends[0]["values"]) if trends else None) if trends else ""
    return render_template("dashboard_staff.html", rows=rows, last=last, risk=risk[:8], n_risk=len(risk),
                           n_high=sum(1 for r in risk if r["level"] == "High"), alerts=alerts, anns=anns,
                           n_students=n_students, n_courses=n_courses, n_staff=n_staff, perf=perf, enr=enr)


# ----------------------------------------------------------------- students
def student_query(scope, q="", campus="", programme=""):
    sql = """SELECT s.*, ca.name AS campus, p.name AS programme, p.code AS pcode FROM students s
        JOIN campuses ca ON ca.id=s.campus_id JOIN programmes p ON p.id=s.programme_id WHERE 1=1"""
    args = []
    if scope:
        sql += " AND s.campus_id=?"; args.append(scope)
    elif campus:
        sql += " AND s.campus_id=?"; args.append(campus)
    if programme:
        sql += " AND s.programme_id=?"; args.append(programme)
    if q:
        sql += " AND (s.full_name LIKE ? OR s.reg_no LIKE ?)"; args += [f"%{q}%", f"%{q}%"]
    return conn().execute(sql + " ORDER BY s.campus_id, s.full_name", args).fetchall()


@app.route("/students")
@login_required("sysadmin", "management", "coordinator")
def students():
    q, campus, prog = request.args.get("q", ""), request.args.get("campus", ""), request.args.get("programme", "")
    rows = student_query(campus_scope(), q, campus, prog)
    return render_template("students.html", rows=rows, q=q, campus=campus, prog=prog,
                           campuses=conn().execute("SELECT * FROM campuses").fetchall(),
                           programmes=conn().execute("SELECT * FROM programmes").fetchall())


def find_duplicate(name, phone, reg_no=None):
    c = conn()
    if reg_no and c.execute("SELECT 1 FROM students WHERE reg_no=?", (reg_no,)).fetchone():
        return "A student with this registration number already exists."
    norm = " ".join(name.lower().split())
    for r in c.execute("SELECT full_name, phone, reg_no FROM students"):
        if " ".join(r["full_name"].lower().split()) == norm and (not phone or not r["phone"] or r["phone"].replace(" ", "") == phone.replace(" ", "")):
            return f"Possible duplicate: {r['full_name']} ({r['reg_no']}) already exists with the same name/phone."
    return None


def next_reg_no(campus_id, year):
    c = conn()
    cname = c.execute("SELECT name FROM campuses WHERE id=?", (campus_id,)).fetchone()["name"]
    n = c.execute("SELECT COUNT(*) n FROM students WHERE campus_id=? AND intake_year=?", (campus_id, year)).fetchone()["n"] + 1
    while True:
        reg = f"IPAM/EM/{cname[:2].upper()}/{year}/{n:03d}"
        if not c.execute("SELECT 1 FROM students WHERE reg_no=?", (reg,)).fetchone():
            return reg
        n += 1


def register_courses(student_id, term):
    """Register a student for the 4 courses of their current stage in the given term."""
    c = conn()
    s = c.execute("SELECT * FROM students WHERE id=?", (student_id,)).fetchone()
    start = {"2025/2026 Semester 1": (2025, 0), "2025/2026 Semester 2": (2025, 1), "2026/2027 Semester 1": (2026, 0)}.get(term)
    if not start or s["intake_year"] > start[0]:
        return 0
    stage = (start[0] - s["intake_year"]) * 2 + start[1] + 1
    n = 0
    for crs in c.execute("SELECT id FROM courses WHERE programme_id=? AND stage=?", (s["programme_id"], stage)):
        cur = c.execute("INSERT OR IGNORE INTO registrations(student_id,course_id,term) VALUES (?,?,?)", (student_id, crs["id"], term))
        n += cur.rowcount
    c.commit()
    return n


@app.route("/students/new", methods=["GET", "POST"])
@login_required("sysadmin", "coordinator")
def student_new():
    c = conn()
    scope = campus_scope()
    if request.method == "POST":
        name = " ".join(request.form.get("full_name", "").split())
        phone = request.form.get("phone", "").strip()
        campus_id = scope or int(request.form.get("campus_id", 0) or 0)
        prog = int(request.form.get("programme_id", 0) or 0)
        year = int(request.form.get("intake_year", 2026) or 2026)
        gender = request.form.get("gender", "")
        if len(name) < 3 or not campus_id or not prog or gender not in ("Male", "Female"):
            flash("Please fill in the name, gender, campus and programme.", "danger")
        else:
            dup = find_duplicate(name, phone)
            if dup and not request.form.get("confirm_duplicate"):
                flash(dup + " Tick the box below if you are sure this is a different person.", "warning")
                return render_template("student_form.html", campuses=c.execute("SELECT * FROM campuses").fetchall(),
                                       programmes=c.execute("SELECT * FROM programmes").fetchall(), form=request.form, dup=True)
            reg = next_reg_no(campus_id, year)
            cur = c.execute("INSERT INTO students(reg_no,full_name,gender,phone,campus_id,programme_id,intake_year) VALUES (?,?,?,?,?,?,?)",
                            (reg, name, gender, phone, campus_id, prog, year))
            sid = cur.lastrowid
            c.execute("INSERT INTO users(username,password_hash,full_name,role,campus_id,student_id) VALUES (?,?,?,?,?,?)",
                      (reg.lower(), generate_password_hash(config.DEFAULT_PASSWORD), name, "student", campus_id, sid))
            c.commit()
            n = register_courses(sid, config.CURRENT_TERM)
            log("register_student", reg)
            flash(f"Student registered: {name} ({reg}). {n} courses registered for {config.CURRENT_TERM}.", "success")
            return redirect(url_for("student_detail", sid=sid))
    return render_template("student_form.html", campuses=c.execute("SELECT * FROM campuses").fetchall(),
                           programmes=c.execute("SELECT * FROM programmes").fetchall(), form=request.form, dup=False)


@app.route("/students/<int:sid>")
@login_required("sysadmin", "management", "coordinator")
def student_detail(sid):
    s = conn().execute("""SELECT s.*, ca.name AS campus, p.name AS programme FROM students s
        JOIN campuses ca ON ca.id=s.campus_id JOIN programmes p ON p.id=s.programme_id WHERE s.id=?""", (sid,)).fetchone()
    if not s or (campus_scope() and s["campus_id"] != campus_scope()):
        abort(404)
    return render_template("student_detail.html", s=s, record=analytics.student_record(sid))


@app.route("/students/<int:sid>/status", methods=["POST"])
@login_required("sysadmin", "coordinator")
def student_status(sid):
    s = conn().execute("SELECT * FROM students WHERE id=?", (sid,)).fetchone()
    if not s or (campus_scope() and s["campus_id"] != campus_scope()):
        abort(404)
    status = request.form.get("status")
    if status in ("Active", "Deferred", "Withdrawn"):
        conn().execute("UPDATE students SET status=? WHERE id=?", (status, sid))
        conn().commit()
        log("student_status", f"{s['reg_no']} -> {status}")
        flash("Student status updated.", "success")
    return redirect(url_for("student_detail", sid=sid))


@app.route("/import", methods=["GET", "POST"])
@login_required("sysadmin")
def import_students():
    """Ingest multi-campus data from a CSV file, checking for duplicates first."""
    report = None
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename.lower().endswith(".csv"):
            flash("Please choose a .csv file.", "danger")
        else:
            text = f.read().decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            need = {"full_name", "gender", "phone", "campus", "programme_code", "intake_year"}
            if not reader.fieldnames or not need.issubset({x.strip() for x in reader.fieldnames}):
                flash("The CSV must have these columns: " + ", ".join(sorted(need)), "danger")
            else:
                c = conn()
                campus_ids = {r["name"].lower(): r["id"] for r in c.execute("SELECT * FROM campuses")}
                prog_ids = {r["code"].upper(): r["id"] for r in c.execute("SELECT * FROM programmes")}
                added, skipped, errors = [], [], []
                for i, row in enumerate(reader, start=2):
                    name = " ".join((row.get("full_name") or "").split())
                    camp = campus_ids.get((row.get("campus") or "").strip().lower())
                    prog = prog_ids.get((row.get("programme_code") or "").strip().upper())
                    gender = (row.get("gender") or "").strip().capitalize()
                    try:
                        year = int(row.get("intake_year"))
                    except (TypeError, ValueError):
                        year = None
                    if len(name) < 3 or not camp or not prog or gender not in ("Male", "Female") or not year:
                        errors.append(f"Row {i}: missing or invalid data ({name or 'no name'})")
                        continue
                    dup = find_duplicate(name, row.get("phone") or "")
                    if dup:
                        skipped.append(f"Row {i}: {name} - {dup}")
                        continue
                    reg = next_reg_no(camp, year)
                    cur = c.execute("INSERT INTO students(reg_no,full_name,gender,phone,campus_id,programme_id,intake_year) VALUES (?,?,?,?,?,?,?)",
                                    (reg, name, gender, row.get("phone", ""), camp, prog, year))
                    c.execute("INSERT INTO users(username,password_hash,full_name,role,campus_id,student_id) VALUES (?,?,?,?,?,?)",
                              (reg.lower(), generate_password_hash(config.DEFAULT_PASSWORD), name, "student", camp, cur.lastrowid))
                    c.commit()
                    register_courses(cur.lastrowid, config.CURRENT_TERM)
                    added.append(f"{name} ({reg})")
                log("import_students", f"added={len(added)} skipped={len(skipped)} errors={len(errors)}")
                report = {"added": added, "skipped": skipped, "errors": errors}
    return render_template("import.html", report=report)


# ----------------------------------------------------------------- marks
def allocation_or_404(aid):
    a = conn().execute("""SELECT al.*, c.code, c.title, ca.name AS campus FROM allocations al JOIN courses c ON c.id=al.course_id
        JOIN campuses ca ON ca.id=al.campus_id WHERE al.id=?""", (aid,)).fetchone()
    if not a:
        abort(404)
    if g.user["role"] == "lecturer" and a["lecturer_id"] != g.user["id"]:
        abort(403)
    if g.user["role"] == "coordinator" and a["campus_id"] != g.user["campus_id"]:
        abort(403)
    return a


def class_rows(a):
    return conn().execute("""SELECT r.*, s.full_name, s.reg_no FROM registrations r JOIN students s ON s.id=r.student_id
        WHERE r.course_id=? AND r.term=? AND s.campus_id=? ORDER BY s.full_name""", (a["course_id"], a["term"], a["campus_id"])).fetchall()


@app.route("/marks/<int:aid>", methods=["GET", "POST"])
@login_required("lecturer", "coordinator", "sysadmin", "management")
def marks(aid):
    a = allocation_or_404(aid)
    can_edit = g.user["role"] == "lecturer" and a["term"] == config.CURRENT_TERM
    c = conn()
    if request.method == "POST":
        if not can_edit:
            abort(403)
        saved, bad = 0, []
        for r in class_rows(a):
            vals = {}
            for field, mx in (("ca", config.CA_MAX), ("exam", config.EXAM_MAX), ("att", 100)):
                raw = request.form.get(f"{field}_{r['id']}", "").strip()
                if raw == "":
                    vals[field] = None
                    continue
                try:
                    v = float(raw)
                    if not 0 <= v <= mx:
                        raise ValueError
                    vals[field] = round(v, 1)
                except ValueError:
                    bad.append(f"{r['full_name']}: {field.upper()} must be a number between 0 and {mx}")
                    vals[field] = "bad"
            if "bad" in vals.values():
                continue
            c.execute("UPDATE registrations SET ca_score=?, exam_score=?, attendance=? WHERE id=?",
                      (vals["ca"], vals["exam"], vals["att"], r["id"]))
            saved += 1
        c.commit()
        log("save_marks", f"{a['code']} {a['campus']} saved={saved}")
        if bad:
            flash("Some rows were not saved: " + "; ".join(bad[:5]), "danger")
        flash(f"{saved} student records saved.", "success")
        return redirect(url_for("marks", aid=aid))
    rows = class_rows(a)
    done = [r for r in rows if r["ca_score"] is not None]
    totals = [r["ca_score"] + r["exam_score"] for r in rows if r["ca_score"] is not None and r["exam_score"] is not None]
    stats = {"n": len(rows), "entered": len(done),
             "avg": round(sum(totals) / len(totals), 1) if totals else None,
             "pass_rate": round(sum(1 for t in totals if t >= config.PASS_MARK) / len(totals) * 100, 1) if totals else None}
    return render_template("marks.html", a=a, rows=rows, can_edit=can_edit, stats=stats)


@app.route("/courses")
@login_required("sysadmin", "management", "coordinator")
def courses():
    scope = campus_scope()
    sql = """SELECT al.id, c.code, c.title, p.code AS pcode, ca.name AS campus, u.full_name AS lecturer,
        (SELECT COUNT(*) FROM registrations r JOIN students s ON s.id=r.student_id
          WHERE r.course_id=al.course_id AND r.term=al.term AND s.campus_id=al.campus_id) AS n
        FROM allocations al JOIN courses c ON c.id=al.course_id JOIN programmes p ON p.id=c.programme_id
        JOIN campuses ca ON ca.id=al.campus_id JOIN users u ON u.id=al.lecturer_id WHERE al.term=?"""
    args = [config.CURRENT_TERM]
    if scope:
        sql += " AND al.campus_id=?"; args.append(scope)
    rows = [r for r in conn().execute(sql + " ORDER BY ca.name, c.code", args).fetchall() if r["n"] > 0]
    return render_template("courses.html", rows=rows)


# ----------------------------------------------------------------- analytics pages
@app.route("/at-risk")
@login_required("sysadmin", "management", "coordinator")
def at_risk():
    level = request.args.get("level", "")
    risk, metrics = analytics.at_risk_students(campus_id=campus_scope())
    if level in ("High", "Medium"):
        risk = [r for r in risk if r["level"] == level]
    return render_template("at_risk.html", risk=risk, metrics=metrics, level=level)


@app.route("/trends")
@login_required("sysadmin", "management", "coordinator")
def trends():
    by = request.args.get("by", "campus")
    by = by if by in ("campus", "programme") else "campus"
    data = analytics.enrolment_trends(by)
    if campus_scope() and by == "campus":
        nm = conn().execute("SELECT name FROM campuses WHERE id=?", (campus_scope(),)).fetchone()["name"]
        data = [d for d in data if d["name"] == nm]
    chart = charts.line_chart(data[0]["years"] + [data[0]["forecast_year"]],
                              [(d["name"].replace(" Campus", ""), d["values"] + [d["forecast"]]) for d in data],
                              title=f"New intake per year by {by} (dashed = forecast)", forecast_from=len(data[0]["values"])) if data else ""
    return render_template("trends.html", data=data, chart=chart, by=by)


def report_data():
    rows, last = analytics.campus_summary()
    scope = campus_scope()
    if scope:
        nm = conn().execute("SELECT name FROM campuses WHERE id=?", (scope,)).fetchone()["name"]
        rows = [r for r in rows if r["campus"] == nm]
    return rows, last


@app.route("/reports")
@login_required("sysadmin", "management", "coordinator")
def reports():
    rows, last = report_data()
    df = analytics.load_frame()
    done = df[df["total"].notna()]
    prog = []
    for (code, name), gdf in done[done["term"] == last].groupby(["programme_code", "programme"]):
        if campus_scope():
            gdf = gdf[gdf["campus_id"] == campus_scope()]
        if len(gdf):
            prog.append({"code": code, "name": name, "students": int(gdf["student_id"].nunique()),
                         "avg": round(float(gdf["total"].mean()), 1),
                         "pass_rate": round(float((gdf["total"] >= config.PASS_MARK).mean() * 100), 1)})
    staffing = conn().execute("""SELECT ca.name AS campus,
        SUM(CASE WHEN u.role='lecturer' THEN 1 ELSE 0 END) AS lecturers,
        SUM(CASE WHEN u.role='coordinator' THEN 1 ELSE 0 END) AS coordinators
        FROM campuses ca LEFT JOIN users u ON u.campus_id=ca.id AND u.active=1 GROUP BY ca.id""").fetchall()
    enrol = conn().execute("""SELECT ca.name AS campus, COUNT(s.id) AS students FROM campuses ca
        LEFT JOIN students s ON s.campus_id=ca.id AND s.status='Active' GROUP BY ca.id""").fetchall()
    staff_map = {r["campus"]: r for r in staffing}
    enrol_map = {r["campus"]: r["students"] for r in enrol}
    if campus_scope():
        keep = {r["campus"] for r in rows}
        staff_map = {k: v for k, v in staff_map.items() if k in keep}
        enrol_map = {k: v for k, v in enrol_map.items() if k in keep}
    pass_chart = charts.bar_chart([r["campus"].replace(" Campus", "") for r in rows],
                                  [(f"Pass rate % ({last})", [r["prev_pass"] for r in rows])], title="Pass rate by campus (last completed term)")
    return render_template("reports.html", rows=rows, last=last, prog=prog, staff=staff_map, enrol=enrol_map,
                           pass_chart=pass_chart, now=datetime.now().strftime("%d %B %Y"))


@app.route("/reports/export/<kind>")
@login_required("sysadmin", "management", "coordinator")
def export(kind):
    out = io.StringIO()
    w = csv.writer(out)
    if kind == "campus":
        rows, last = report_data()
        w.writerow(["Campus", "Students (current term)", f"Pass rate % ({last})", f"Average mark ({last})", "Current avg CA %", "Current avg attendance %"])
        for r in rows:
            w.writerow([r["campus"], r["students"], r["prev_pass"], r["prev_avg"], r["cur_ca"], r["cur_att"]])
    elif kind == "at-risk":
        risk, _ = analytics.at_risk_students(campus_id=campus_scope())
        w.writerow(["Reg No", "Name", "Campus", "Programme", "Avg CA %", "Attendance %", "Risk", "Level", "Reasons"])
        for r in risk:
            w.writerow([r["reg_no"], r["name"], r["campus"], r["programme"], r["ca_avg"], r["attendance"], r["risk"], r["level"], "; ".join(r["reasons"])])
    elif kind == "students":
        w.writerow(["Reg No", "Name", "Gender", "Campus", "Programme", "Intake", "Status"])
        for s in student_query(campus_scope()):
            w.writerow([s["reg_no"], s["full_name"], s["gender"], s["campus"], s["pcode"], s["intake_year"], s["status"]])
    else:
        abort(404)
    log("export", kind)
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=iamdsp_{kind}.csv"})


# ----------------------------------------------------------------- announcements
@app.route("/announcements", methods=["GET", "POST"])
@login_required()
def announcements():
    c = conn()
    if request.method == "POST":
        if g.user["role"] not in ("sysadmin", "management", "coordinator"):
            abort(403)
        title, body = request.form.get("title", "").strip(), request.form.get("body", "").strip()
        campus_id = campus_scope() or (int(request.form["campus_id"]) if request.form.get("campus_id") else None)
        if not title or not body:
            flash("Please write a title and a message.", "danger")
        else:
            c.execute("INSERT INTO announcements(title,body,campus_id,posted_by,posted_at) VALUES (?,?,?,?,?)",
                      (title, body, campus_id, g.user["id"], datetime.now().strftime("%Y-%m-%d %H:%M")))
            c.commit()
            log("announcement", title)
            flash("Announcement posted.", "success")
        return redirect(url_for("announcements"))
    rows = c.execute("""SELECT a.*, u.full_name AS author, ca.name AS campus FROM announcements a JOIN users u ON u.id=a.posted_by
        LEFT JOIN campuses ca ON ca.id=a.campus_id WHERE a.campus_id IS NULL OR a.campus_id=? ORDER BY a.posted_at DESC""",
                     (g.user["campus_id"],)).fetchall()
    return render_template("announcements.html", rows=rows, campuses=c.execute("SELECT * FROM campuses").fetchall())


# ----------------------------------------------------------------- student portal
@app.route("/my-record")
@login_required("student")
def my_record():
    s = conn().execute("""SELECT s.*, ca.name AS campus, p.name AS programme FROM students s
        JOIN campuses ca ON ca.id=s.campus_id JOIN programmes p ON p.id=s.programme_id WHERE s.id=?""", (g.user["student_id"],)).fetchone()
    regs = conn().execute("SELECT COUNT(*) n FROM registrations WHERE student_id=? AND term=?", (s["id"], config.CURRENT_TERM)).fetchone()["n"]
    anns = conn().execute("""SELECT a.*, u.full_name AS author FROM announcements a JOIN users u ON u.id=a.posted_by
        WHERE a.campus_id IS NULL OR a.campus_id=? ORDER BY a.posted_at DESC LIMIT 5""", (s["campus_id"],)).fetchall()
    return render_template("my_record.html", s=s, record=analytics.student_record(s["id"]), regs=regs, anns=anns)


# ----------------------------------------------------------------- administration
@app.route("/admin/users", methods=["GET", "POST"])
@login_required("sysadmin")
def admin_users():
    c = conn()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            uname = request.form.get("username", "").strip().lower().replace(" ", "")
            full = request.form.get("full_name", "").strip()
            role = request.form.get("role")
            camp = request.form.get("campus_id") or None
            pw = request.form.get("password", "")
            if role not in ("management", "coordinator", "lecturer", "sysadmin") or not uname or not full or len(pw) < 8:
                flash("Fill in all fields. The password must have at least 8 characters.", "danger")
            elif role in ("coordinator", "lecturer") and not camp:
                flash("Coordinators and lecturers must belong to a campus.", "danger")
            elif c.execute("SELECT 1 FROM users WHERE username=?", (uname,)).fetchone():
                flash("That username is already used.", "danger")
            else:
                c.execute("INSERT INTO users(username,password_hash,full_name,role,campus_id) VALUES (?,?,?,?,?)",
                          (uname, generate_password_hash(pw), full, role, camp))
                c.commit()
                log("create_user", uname)
                flash(f"Account created for {full}.", "success")
        elif action == "toggle":
            uid = int(request.form.get("uid", 0))
            if uid == g.user["id"]:
                flash("You cannot disable your own account.", "danger")
            else:
                c.execute("UPDATE users SET active = 1 - active WHERE id=?", (uid,))
                c.commit()
                log("toggle_user", str(uid))
                flash("Account updated.", "success")
        elif action == "reset":
            uid = int(request.form.get("uid", 0))
            if uid != g.user["id"]:
                c.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(config.DEFAULT_PASSWORD), uid))
                c.commit()
                log("reset_password", str(uid))
                flash("Password reset to the default password.", "success")
        return redirect(url_for("admin_users"))
    rows = c.execute("""SELECT u.*, ca.name AS campus FROM users u LEFT JOIN campuses ca ON ca.id=u.campus_id
        WHERE u.role != 'student' ORDER BY u.role, u.full_name""").fetchall()
    return render_template("admin_users.html", rows=rows, campuses=c.execute("SELECT * FROM campuses").fetchall())


@app.route("/admin/campuses", methods=["GET", "POST"])
@login_required("sysadmin")
def admin_campuses():
    c = conn()
    if request.method == "POST":
        name, loc = request.form.get("name", "").strip(), request.form.get("location", "").strip()
        if not name or not loc:
            flash("Please enter the campus name and location.", "danger")
        elif c.execute("SELECT 1 FROM campuses WHERE LOWER(name)=?", (name.lower(),)).fetchone():
            flash("A campus with that name already exists.", "danger")
        else:
            c.execute("INSERT INTO campuses(name, location) VALUES (?,?)", (name, loc))
            c.commit()
            log("create_campus", name)
            flash("Campus added.", "success")
        return redirect(url_for("admin_campuses"))
    rows = c.execute("""SELECT ca.*, (SELECT COUNT(*) FROM students s WHERE s.campus_id=ca.id) AS students,
        (SELECT COUNT(*) FROM users u WHERE u.campus_id=ca.id AND u.role!='student') AS staff FROM campuses ca""").fetchall()
    return render_template("admin_campuses.html", rows=rows)


@app.route("/admin/audit")
@login_required("sysadmin")
def admin_audit():
    rows = conn().execute("""SELECT a.*, u.username FROM audit_log a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 100""").fetchall()
    return render_template("admin_audit.html", rows=rows)


@app.route("/account", methods=["GET", "POST"])
@login_required()
def account():
    if request.method == "POST":
        old, new, again = request.form.get("old", ""), request.form.get("new", ""), request.form.get("again", "")
        if not check_password_hash(g.user["password_hash"], old):
            flash("Your old password is not correct.", "danger")
        elif len(new) < 8 or new != again:
            flash("The new password must have at least 8 characters and both boxes must match.", "danger")
        else:
            conn().execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new), g.user["id"]))
            conn().commit()
            log("change_password")
            flash("Password changed.", "success")
    return render_template("account.html")


if __name__ == "__main__":
    print("\n  IAMDSP is starting...  Open your browser and go to:  http://127.0.0.1:5000\n")
    app.run(host="127.0.0.1", port=5000, debug=False)
