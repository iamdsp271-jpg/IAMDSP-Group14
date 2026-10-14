"""Decision Support and Analytics engine (simple, explainable methods).

1. At-risk prediction: logistic regression (scikit-learn) trained on COMPLETED
   past terms, then used on the CURRENT term (before exams) using continuous
   assessment (CA), attendance and the student's previous average.
2. Enrolment trend: straight-line regression per campus / programme.
3. Early-warning alerts: rule-based checks, each with a plain-language reason.
"""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, roc_auc_score
import config
from db import get_db

HIGH, MEDIUM = 0.50, 0.30


def grade(total):
    if total is None:
        return "-"
    return "A" if total >= 70 else "B" if total >= 60 else "C" if total >= 50 else "D" if total >= 40 else "F"


def load_frame(term=None):
    """All registrations with student/course/campus information as a DataFrame."""
    conn = get_db()
    df = pd.read_sql_query("""
        SELECT r.id AS reg_id, r.student_id, r.course_id, r.term, r.ca_score, r.exam_score, r.attendance,
               s.reg_no, s.full_name, s.campus_id, s.programme_id, s.intake_year,
               c.code AS course_code, c.title AS course_title,
               ca.name AS campus, p.name AS programme, p.code AS programme_code
        FROM registrations r
        JOIN students s ON s.id = r.student_id
        JOIN courses c ON c.id = r.course_id
        JOIN campuses ca ON ca.id = s.campus_id
        JOIN programmes p ON p.id = s.programme_id
    """, conn)
    conn.close()
    df["ca_pct"] = df["ca_score"] / config.CA_MAX * 100
    df["total"] = df["ca_score"] + df["exam_score"]
    if term:
        df = df[df["term"] == term]
    return df


def _add_previous_average(df):
    """Attach each student's average total from their most recent completed term."""
    done = df[df["total"].notna()]
    avg = done.groupby(["student_id", "term"])["total"].mean().reset_index()
    order = {t: i for i, t in enumerate(sorted(df["term"].unique()))}
    avg["o"] = avg["term"].map(order)
    prev = {}
    for _, row in avg.iterrows():
        prev[(row["student_id"], row["o"] + 1)] = row["total"]
    df = df.copy()
    df["term_order"] = df["term"].map(order)
    df["prev_avg"] = [prev.get((s, o)) for s, o in zip(df["student_id"], df["term_order"])]
    return df


FEATURES = ["ca_pct", "attendance", "prev_avg"]


def train_model():
    """Train on completed terms. Returns (model, fill_value, metrics dict)."""
    df = _add_previous_average(load_frame())
    train = df[df["total"].notna()].copy()
    fill = float(train["prev_avg"].mean()) if train["prev_avg"].notna().any() else 60.0
    train["prev_avg"] = train["prev_avg"].fillna(fill)
    X = train[FEATURES].values
    y = (train["total"] < config.PASS_MARK).astype(int).values
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, random_state=42, stratify=y)
    model = LogisticRegression(max_iter=1000)
    model.fit(Xtr, ytr)
    prob = model.predict_proba(Xte)[:, 1]
    metrics = {
        "training_rows": int(len(Xtr)), "test_rows": int(len(Xte)),
        "accuracy": round(float(accuracy_score(yte, model.predict(Xte))), 3),
        "auc": round(float(roc_auc_score(yte, prob)), 3),
        "fail_rate": round(float(y.mean()), 3),
    }
    model.fit(X, y)  # final model uses all completed data
    return model, fill, metrics


def at_risk_students(term=None, campus_id=None, min_level=MEDIUM):
    """List of students predicted to be at risk in the current term, with reasons."""
    term = term or config.CURRENT_TERM
    model, fill, metrics = train_model()
    df = _add_previous_average(load_frame())
    cur = df[df["term"] == term].copy()
    # courses where CA or attendance has not been entered yet cannot be predicted
    cur = cur[cur["ca_pct"].notna() & cur["attendance"].notna()]
    if campus_id:
        cur = cur[cur["campus_id"] == campus_id]
    if cur.empty:
        return [], metrics
    cur["prev_filled"] = cur["prev_avg"].fillna(fill)
    cur["risk"] = model.predict_proba(cur[["ca_pct", "attendance", "prev_filled"]].values)[:, 1]
    out = []
    for sid, g in cur.groupby("student_id"):
        worst = g.sort_values("risk", ascending=False).iloc[0]
        ca_avg, att_avg = g["ca_pct"].mean(), g["attendance"].mean()
        prev = g["prev_avg"].iloc[0]
        score = float(g["risk"].mean())
        if score < min_level:
            continue
        reasons = []
        if ca_avg < 50:
            reasons.append(f"average CA score is {ca_avg:.0f}% (below the 50% pass mark)")
        if att_avg < 65:
            reasons.append(f"attendance is {att_avg:.0f}% (below 65%)")
        if pd.notna(prev) and prev < 55:
            reasons.append(f"previous term average was only {prev:.0f}%")
        if pd.notna(prev) and ca_avg < prev - 8:
            reasons.append(f"CA average has dropped by {prev - ca_avg:.0f} points compared with the previous term")
        weak = g[g["risk"] >= HIGH]
        if len(weak):
            reasons.append("weak in " + ", ".join(weak["course_code"].tolist()))
        if not reasons:
            reasons.append("combination of CA score and attendance is close to patterns seen in students who failed before")
        out.append({
            "student_id": int(sid), "reg_no": worst["reg_no"], "name": worst["full_name"], "campus": worst["campus"],
            "programme": worst["programme_code"], "ca_avg": round(float(ca_avg), 1), "attendance": round(float(att_avg), 1),
            "prev_avg": None if pd.isna(prev) else round(float(prev), 1),
            "risk": round(score, 2), "level": "High" if score >= HIGH else "Medium", "reasons": reasons,
        })
    out.sort(key=lambda r: r["risk"], reverse=True)
    return out, metrics


def enrolment_series():
    """Yearly intake per campus: history table (2020-2024) + live students (2025-2026)."""
    conn = get_db()
    hist = pd.read_sql_query("""SELECT ca.name AS campus, p.code AS programme, h.year, h.intake
        FROM enrolment_history h JOIN campuses ca ON ca.id=h.campus_id JOIN programmes p ON p.id=h.programme_id""", conn)
    live = pd.read_sql_query("""SELECT ca.name AS campus, p.code AS programme, s.intake_year AS year, COUNT(*) AS intake
        FROM students s JOIN campuses ca ON ca.id=s.campus_id JOIN programmes p ON p.id=s.programme_id
        GROUP BY ca.name, p.code, s.intake_year""", conn)
    conn.close()
    return pd.concat([hist, live], ignore_index=True)


def enrolment_trends(by="campus"):
    """Per campus (or programme): yearly totals, next-year forecast, % change and a warning flag."""
    df = enrolment_series()
    tot = df.groupby([by, "year"])["intake"].sum().reset_index()
    result = []
    for name, g in tot.groupby(by):
        g = g.sort_values("year")
        years, vals = g["year"].values, g["intake"].values
        slope, intercept = np.polyfit(years, vals, 1)
        nxt = int(years.max()) + 1
        forecast = max(0, round(float(slope * nxt + intercept)))
        change = (vals[-1] - vals[-2]) / vals[-2] * 100 if len(vals) > 1 and vals[-2] else 0.0
        result.append({"name": name, "years": [int(y) for y in years], "values": [int(v) for v in vals],
                       "forecast_year": nxt, "forecast": forecast, "change": round(float(change), 1),
                       "slope": round(float(slope), 2), "warning": bool(change <= -15)})
    return result


def campus_summary(term=None):
    """Pass rate, average mark, attendance per campus for a completed term and CA/attendance for the current term."""
    term = term or config.CURRENT_TERM
    df = load_frame()
    rows = []
    completed = sorted(t for t in df["term"].unique() if df[(df["term"] == t)]["total"].notna().all())
    last_done = completed[-1] if completed else None
    for camp, g in df.groupby("campus"):
        cur = g[g["term"] == term]
        prev = g[g["term"] == last_done] if last_done else g.iloc[0:0]
        rows.append({
            "campus": camp, "students": int(cur["student_id"].nunique()),
            "cur_ca": round(float(cur["ca_pct"].mean()), 1) if len(cur) else None,
            "cur_att": round(float(cur["attendance"].mean()), 1) if len(cur) else None,
            "prev_ca": round(float(prev["ca_pct"].mean()), 1) if len(prev) else None,
            "prev_att": round(float(prev["attendance"].mean()), 1) if len(prev) else None,
            "prev_pass": round(float((prev["total"] >= config.PASS_MARK).mean() * 100), 1) if len(prev) else None,
            "prev_avg": round(float(prev["total"].mean()), 1) if len(prev) else None,
        })
    return rows, last_done


def early_warnings():
    """Rule-based alerts for management, each with a reason."""
    alerts = []
    rows, last = campus_summary()
    for r in rows:
        if r["cur_ca"] is not None and r["prev_ca"] is not None and r["prev_ca"] - r["cur_ca"] >= 5:
            alerts.append({"type": "Performance", "campus": r["campus"],
                           "message": f"Average CA score is {r['cur_ca']}% this term compared with {r['prev_ca']}% in {last} (a drop of {r['prev_ca'] - r['cur_ca']:.1f} points)."})
        if r["cur_att"] is not None and r["prev_att"] is not None and r["prev_att"] - r["cur_att"] >= 5:
            alerts.append({"type": "Attendance", "campus": r["campus"],
                           "message": f"Average attendance is {r['cur_att']}% compared with {r['prev_att']}% in {last}."})
    for t in enrolment_trends("campus"):
        if t["warning"]:
            alerts.append({"type": "Enrolment", "campus": t["name"],
                           "message": f"New intake fell by {abs(t['change'])}% in {t['years'][-1]} (from {t['values'][-2]} to {t['values'][-1]} students)."})
    return alerts


def student_record(student_id):
    """Course results of one student, newest term first."""
    df = load_frame()
    g = df[df["student_id"] == student_id].sort_values(["term", "course_code"], ascending=[False, True])
    rows = []
    for _, r in g.iterrows():
        total = None if pd.isna(r["total"]) else round(float(r["total"]), 1)
        rows.append({"term": r["term"], "code": r["course_code"], "title": r["course_title"],
                     "ca": None if pd.isna(r["ca_score"]) else float(r["ca_score"]),
                     "exam": None if pd.isna(r["exam_score"]) else float(r["exam_score"]),
                     "total": total, "grade": grade(total),
                     "status": "-" if total is None else ("Pass" if total >= config.PASS_MARK else "Fail"),
                     "attendance": None if pd.isna(r["attendance"]) else float(r["attendance"])})
    return rows
