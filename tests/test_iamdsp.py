"""Automated tests for IAMDSP.  Run with:  python -m unittest discover -s tests -v
The tests use a temporary copy of the database, so your real data is never touched.
"""
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

_tmp = tempfile.mkdtemp()
config.DATABASE = os.path.join(_tmp, "test.db")

import analytics  # noqa: E402
import app as iamdsp  # noqa: E402
import db  # noqa: E402


def csrf(client):
    client.get("/login")
    with client.session_transaction() as s:
        return s.get("csrf")


def login(client, user, pw):
    return client.post("/login", data={"username": user, "password": pw, "csrf_token": csrf(client)})


def post(client, url, data=None, **kw):
    with client.session_transaction() as s:
        tok = s.get("csrf")
    d = dict(data or {})
    d["csrf_token"] = tok
    return client.post(url, data=d, **kw)


class IAMDSPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.seed_database()
        iamdsp.app.config["TESTING"] = True

    def client(self, user=None, pw=config.DEFAULT_PASSWORD):
        c = iamdsp.app.test_client()
        if user:
            login(c, user, pw)
        return c

    # ------------------------------------------------------------ security
    def test_01_group_login(self):
        """TC01|Log in with the group username (Group Fourteen) and passcode|Dashboard opens"""
        c = self.client()
        r = login(c, "Group Fourteen", config.GROUP_PASSWORD)
        self.assertEqual(r.status_code, 302)
        self.assertIn(b"Management Dashboard", c.get("/dashboard").data)

    def test_02_wrong_password(self):
        """TC02|Log in with a wrong password|Login refused with an error message"""
        c = self.client()
        r = login(c, "groupfourteen", "wrong")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Wrong username or password", r.data)

    def test_03_protected_pages(self):
        """TC03|Open the dashboard without logging in|Redirected to the login page"""
        r = self.client().get("/dashboard")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_04_lecturer_blocked_from_admin(self):
        """TC04|Lecturer tries to open User Accounts|Access denied (403)"""
        self.assertEqual(self.client("samuel.gbani").get("/admin/users").status_code, 403)

    def test_05_student_blocked_from_students(self):
        """TC05|Student tries to open the student list|Access denied (403)"""
        self.assertEqual(self.client("ipam/em/fr/2025/001").get("/students").status_code, 403)

    def test_06_csrf(self):
        """TC06|Submit a form without the security token|Request rejected (400)"""
        c = self.client("michael.sillah")
        r = c.post("/students/new", data={"full_name": "Test Person"})
        self.assertEqual(r.status_code, 400)

    def test_07_change_password_wrong_old(self):
        """TC07|Change password with a wrong old password|Change refused"""
        c = self.client("michael.sillah")
        r = post(c, "/account", {"old": "bad", "new": "NewPass123", "again": "NewPass123"})
        self.assertIn(b"old password is not correct", r.data)

    # ------------------------------------------------------------ registration
    def test_10_register_student(self):
        """TC10|Coordinator registers a new student|Student saved, reg. no. created, 4 courses registered, student login created"""
        c = self.client("michael.sillah")
        r = post(c, "/students/new", {"full_name": "Abubakarr Tejan Kallon", "gender": "Male", "phone": "+232 76 555111",
                                     "programme_id": "1", "intake_year": "2026"}, follow_redirects=True)
        self.assertIn(b"Student registered", r.data)
        conn = db.get_db()
        s = conn.execute("SELECT * FROM students WHERE full_name='Abubakarr Tejan Kallon'").fetchone()
        self.assertIsNotNone(s)
        self.assertEqual(s["campus_id"], 1)  # coordinator's own campus
        n = conn.execute("SELECT COUNT(*) n FROM registrations WHERE student_id=? AND term=?", (s["id"], config.CURRENT_TERM)).fetchone()["n"]
        self.assertEqual(n, 4)
        self.assertIsNotNone(conn.execute("SELECT 1 FROM users WHERE student_id=?", (s["id"],)).fetchone())
        conn.close()
        c2 = self.client()
        login(c2, s["reg_no"].lower(), config.DEFAULT_PASSWORD)
        self.assertIn(b"Abubakarr Tejan Kallon", c2.get("/my-record").data)

    def test_11_duplicate_detected(self):
        """TC11|Register a student whose name already exists|Duplicate warning shown, nothing saved"""
        c = self.client("michael.sillah")
        conn = db.get_db()
        name = conn.execute("SELECT full_name FROM students WHERE campus_id=1 LIMIT 1").fetchone()["full_name"]
        before = conn.execute("SELECT COUNT(*) n FROM students").fetchone()["n"]
        r = post(c, "/students/new", {"full_name": name, "gender": "Male", "phone": "", "programme_id": "1", "intake_year": "2026"})
        self.assertIn(b"Possible duplicate", r.data)
        after = conn.execute("SELECT COUNT(*) n FROM students").fetchone()["n"]
        conn.close()
        self.assertEqual(before, after)

    def test_12_incomplete_form(self):
        """TC12|Submit the registration form with missing fields|Validation message, nothing saved"""
        c = self.client("michael.sillah")
        r = post(c, "/students/new", {"full_name": "A", "gender": "", "programme_id": ""})
        self.assertIn(b"Please fill in", r.data)

    def test_13_coordinator_campus_limit(self):
        """TC13|Coordinator opens a student from another campus|Page not found (404)"""
        conn = db.get_db()
        other = conn.execute("SELECT id FROM students WHERE campus_id=2 LIMIT 1").fetchone()["id"]
        conn.close()
        self.assertEqual(self.client("michael.sillah").get(f"/students/{other}").status_code, 404)

    def test_14_csv_import(self):
        """TC14|Import a campus CSV containing new, duplicate and invalid rows|New rows added, duplicate skipped, invalid rows reported"""
        c = self.client("groupfourteen", config.GROUP_PASSWORD)
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample_data", "sample_campus_students.csv")
        with open(path, "rb") as f:
            data = {"file": (io.BytesIO(f.read()), "sample.csv")}
        r = post(c, "/import", data, content_type="multipart/form-data")
        txt = r.data.decode()
        self.assertIn("Added (6)", txt)
        self.assertIn("possible duplicates (1)", txt)
        self.assertIn("Rows with errors (2)", txt)

    # ------------------------------------------------------------ marks
    def _alloc_of(self, username):
        conn = db.get_db()
        uid = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
        rows = conn.execute("""SELECT al.id FROM allocations al WHERE al.lecturer_id=? AND al.term=? AND EXISTS
            (SELECT 1 FROM registrations r JOIN students s ON s.id=r.student_id WHERE r.course_id=al.course_id AND r.term=al.term AND s.campus_id=al.campus_id)""",
                            (uid, config.CURRENT_TERM)).fetchall()
        conn.close()
        return rows[0]["id"]

    def test_20_save_marks(self):
        """TC20|Lecturer saves valid CA, exam and attendance marks|Marks stored in the database"""
        aid = self._alloc_of("samuel.gbani")
        c = self.client("samuel.gbani")
        conn = db.get_db()
        a = conn.execute("SELECT * FROM allocations WHERE id=?", (aid,)).fetchone()
        reg = conn.execute("""SELECT r.id FROM registrations r JOIN students s ON s.id=r.student_id
            WHERE r.course_id=? AND r.term=? AND s.campus_id=? LIMIT 1""", (a["course_id"], a["term"], a["campus_id"])).fetchone()["id"]
        r = post(c, f"/marks/{aid}", {f"ca_{reg}": "31.5", f"exam_{reg}": "42", f"att_{reg}": "88"}, follow_redirects=True)
        self.assertIn(b"records saved", r.data)
        row = conn.execute("SELECT * FROM registrations WHERE id=?", (reg,)).fetchone()
        conn.close()
        self.assertEqual((row["ca_score"], row["exam_score"], row["attendance"]), (31.5, 42.0, 88.0))

    def test_21_invalid_marks(self):
        """TC21|Lecturer enters CA = 45 (maximum is 40)|Mark rejected with an error, old value kept"""
        aid = self._alloc_of("samuel.gbani")
        c = self.client("samuel.gbani")
        conn = db.get_db()
        a = conn.execute("SELECT * FROM allocations WHERE id=?", (aid,)).fetchone()
        reg = conn.execute("""SELECT r.id, r.ca_score FROM registrations r JOIN students s ON s.id=r.student_id
            WHERE r.course_id=? AND r.term=? AND s.campus_id=? LIMIT 1""", (a["course_id"], a["term"], a["campus_id"])).fetchone()
        r = post(c, f"/marks/{aid}", {f"ca_{reg['id']}": "45"}, follow_redirects=True)
        self.assertIn(b"must be a number between 0 and 40", r.data)
        now = conn.execute("SELECT ca_score FROM registrations WHERE id=?", (reg["id"],)).fetchone()["ca_score"]
        conn.close()
        self.assertEqual(now, reg["ca_score"])

    def test_22_other_lecturer_blocked(self):
        """TC22|Lecturer opens a class that belongs to another lecturer|Access denied (403)"""
        aid = self._alloc_of("mohamed.turay")
        self.assertEqual(self.client("samuel.gbani").get(f"/marks/{aid}").status_code, 403)

    # ------------------------------------------------------------ student portal
    def test_30_student_sees_own_record(self):
        """TC30|Student logs in and opens My Academic Record|Own name, courses and results are shown"""
        conn = db.get_db()
        s = conn.execute("SELECT reg_no, full_name FROM students WHERE intake_year=2025 LIMIT 1").fetchone()
        conn.close()
        c = self.client(s["reg_no"].lower())
        data = c.get("/my-record").data
        self.assertIn(s["full_name"].encode(), data)
        self.assertIn(b"2025/2026 Semester 1", data)

    # ------------------------------------------------------------ analytics
    def test_40_grade_boundaries(self):
        """TC40|Grade function at boundaries (70, 60, 50, 40, 39.9)|A, B, C, D, F"""
        self.assertEqual([analytics.grade(x) for x in (70, 60, 50, 40, 39.9)], ["A", "B", "C", "D", "F"])

    def test_41_at_risk_has_reasons(self):
        """TC41|Open the at-risk list|Students flagged, every student has at least one reason"""
        risk, _ = analytics.at_risk_students()
        self.assertGreater(len(risk), 0)
        self.assertTrue(all(r["reasons"] for r in risk))

    def test_42_model_quality(self):
        """TC42|Check prediction accuracy on unseen records|Accuracy at least 80%"""
        _, m = analytics.at_risk_students()
        self.assertGreaterEqual(m["accuracy"], 0.80)

    def test_43_enrolment_warning(self):
        """TC43|Check enrolment trend for Makeni Campus|Warning raised for falling intake"""
        t = {x["name"]: x for x in analytics.enrolment_trends("campus")}
        self.assertTrue(t["Makeni Campus"]["warning"])
        self.assertFalse(t["Freetown Campus"]["warning"])

    def test_44_pass_rate_correct(self):
        """TC44|Compare campus pass rate shown by the system with a direct database calculation|Values match"""
        rows, last = analytics.campus_summary()
        conn = db.get_db()
        for r in rows:
            q = conn.execute("""SELECT AVG(CASE WHEN r.ca_score+r.exam_score>=? THEN 100.0 ELSE 0 END) p
                FROM registrations r JOIN students s ON s.id=r.student_id JOIN campuses c ON c.id=s.campus_id
                WHERE r.term=? AND c.name=?""", (config.PASS_MARK, last, r["campus"])).fetchone()["p"]
            self.assertAlmostEqual(q, r["prev_pass"], places=1)
        conn.close()

    def test_45_early_warnings(self):
        """TC45|Open early-warning alerts on the dashboard|Alerts exist for Makeni (performance and enrolment)"""
        types = {(a["type"], a["campus"]) for a in analytics.early_warnings()}
        self.assertIn(("Performance", "Makeni Campus"), types)
        self.assertIn(("Enrolment", "Makeni Campus"), types)

    # ------------------------------------------------------------ reports & admin
    def test_50_export_csv(self):
        """TC50|Management downloads the campus summary CSV|CSV file with header and four campus rows"""
        r = self.client("ibrahim.kamara").get("/reports/export/campus")
        self.assertEqual(r.mimetype, "text/csv")
        self.assertEqual(len(r.data.decode().strip().splitlines()), 5)

    def test_51_create_user(self):
        """TC51|System administrator creates a lecturer account|Account created and can log in"""
        c = self.client("groupfourteen", config.GROUP_PASSWORD)
        r = post(c, "/admin/users", {"action": "create", "full_name": "Test Lecturer", "username": "test.lecturer", "role": "lecturer",
                                     "campus_id": "1", "password": "Secret1234"}, follow_redirects=True)
        self.assertIn(b"Account created", r.data)
        c2 = self.client()
        self.assertEqual(login(c2, "test.lecturer", "Secret1234").status_code, 302)

    def test_52_duplicate_username(self):
        """TC52|Create an account with a username that already exists|Refused with an error"""
        c = self.client("groupfourteen", config.GROUP_PASSWORD)
        r = post(c, "/admin/users", {"action": "create", "full_name": "X Y", "username": "samuel.gbani", "role": "lecturer",
                                     "campus_id": "1", "password": "Secret1234"}, follow_redirects=True)
        self.assertIn(b"already used", r.data)

    def test_53_management_cannot_admin(self):
        """TC53|Management user opens User Accounts|Access denied (403)"""
        self.assertEqual(self.client("ibrahim.kamara").get("/admin/users").status_code, 403)

    def test_54_announcement(self):
        """TC54|Coordinator posts an announcement|Announcement visible to students of that campus"""
        c = self.client("michael.sillah")
        post(c, "/announcements", {"title": "Test Notice", "body": "Classes resume Monday."})
        conn = db.get_db()
        s = conn.execute("SELECT reg_no FROM students WHERE campus_id=1 AND intake_year=2025 LIMIT 1").fetchone()
        conn.close()
        self.assertIn(b"Test Notice", self.client(s["reg_no"].lower()).get("/my-record").data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
