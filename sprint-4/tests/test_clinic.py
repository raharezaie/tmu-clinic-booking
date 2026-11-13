"""Clinic side: appointment status changes, admin and doctor dashboards, weekly hours, CSV, demo data."""
import sqlite3
from datetime import date, timedelta

from conftest import in_minutes

TODAY = date.today


def todays(site, patient_n, time, doctor=1, status="booked"):
    return site.appointment(site.patient(patient_n).user_id, doctor, TODAY(), time, status)


# ---------- Status changes ----------
def test_front_desk_checks_in_only_todays_booked_patients(site, monday):
    admin = site.admin()
    appt = todays(site, 1, "23:30")
    assert "checked in" in admin.text(f"/admin/appointments/{appt}/check-in", from_page="/admin/dashboard")
    assert "Only booked" in admin.text(f"/admin/appointments/{appt}/check-in", from_page="/admin/dashboard")
    future = site.appointment(site.patient(2).user_id, 1, monday, "09:00")
    assert "on the day of their appointment" in admin.text(f"/admin/appointments/{future}/check-in",
                                                           from_page="/admin/dashboard")


def test_doctor_completes_a_visit_with_private_notes(site):
    appt = todays(site, 1, "00:00", status="checked_in")
    page = site.doctor(1).text(f"/doctor/appointments/{appt}/complete", dict(notes="Advised rest."),
                               from_page="/doctor/dashboard")
    assert "marked complete" in page and "Advised rest." in page
    assert "Advised rest." not in site.patient(1).page(f"/appointments/{appt}")  # staff only


def test_future_visits_cannot_be_completed(site, monday):
    appt = site.appointment(site.patient(1).user_id, 1, monday, "09:00")
    page = site.doctor(1).text(f"/doctor/appointments/{appt}/complete", from_page="/doctor/dashboard")
    assert "future day" in page


def test_no_show_only_after_the_start_time(site):
    started, later = todays(site, 1, "00:00"), todays(site, 2, "23:59")
    doctor = site.doctor(1)
    assert "after the appointment" in doctor.text(f"/doctor/appointments/{later}/no-show", from_page="/doctor/dashboard")
    assert "no-show" in doctor.text(f"/doctor/appointments/{started}/no-show", from_page="/doctor/dashboard")
    assert site.one("SELECT status FROM appointments WHERE id = ?", (started,))["status"] == "no_show"


def test_doctors_only_manage_their_own_appointments(site):
    appt = todays(site, 1, "00:00")
    assert site.doctor(3).post(f"/doctor/appointments/{appt}/complete", from_page="/doctor/dashboard",
                               follow=False).status_code == 404


def test_checked_in_slots_cannot_be_double_booked(site, monday):
    site.appointment(site.patient(1).user_id, 1, monday, "09:00", status="checked_in")
    try:
        site.appointment(site.patient(2).user_id, 1, monday, "09:00")
        assert False, "database allowed a second booking"
    except sqlite3.IntegrityError:
        pass
    assert 'value="09:00"' not in site.patient(3).page(f"/book?date={monday}")


# ---------- Dashboards ----------
def test_admin_dashboard_counts_the_day(site):
    todays(site, 1, "00:00", status="completed")
    todays(site, 2, "00:30", status="no_show")
    todays(site, 3, "01:00", status="cancelled")
    todays(site, 4, "23:30")
    page = site.admin().page("/admin/dashboard")
    assert "Clinic summary" in page and "Last 7 days" in page
    assert "<dd>3<small> of" in page  # cancelled one isn't counted
    assert "Check in" in page and "Download CSV" in page


def test_csv_export_lists_the_days_appointments_safely(site):
    """Sprint 4 improvement. Reasons starting with '=' are escaped so spreadsheets don't run them."""
    site.sql("INSERT INTO appointments (patient_id, doctor_id, appt_date, start_time, reason) VALUES (?, 1, ?, '10:00', ?)",
             (site.patient(1).user_id, TODAY().isoformat(), "=HYPERLINK(\"http://x\")"))
    r = site.admin().get("/admin/dashboard.csv")
    body = r.get_data(as_text=True)
    assert r.mimetype == "text/csv" and "attachment" in r.headers["Content-Disposition"]
    assert "Patient 1" in body and "Dr. Priya Raman" in body and "'=HYPERLINK" in body
    assert site.patient(2).get("/admin/dashboard.csv").status_code == 403


def test_doctor_dashboard_shows_only_their_own_day(site):
    todays(site, 1, "10:00", doctor=1)
    todays(site, 2, "13:00", doctor=3)
    page = site.doctor(1).page("/doctor/dashboard")
    assert "Patient 1" in page and "Patient 2" not in page and "Walk-ins" in page


def test_doctor_dashboard_lists_the_wait_list(site, monday):
    site.sql("INSERT INTO waitlist (patient_id, doctor_id, wait_date) VALUES (?, 1, ?)",
             (site.patient(1).user_id, monday.isoformat()))
    assert "Patient 1" in site.doctor(1).page(f"/doctor/dashboard?date={monday}")


# ---------- Weekly hours ----------
def hours(b, path="/doctor/hours", **form):
    return b.text(path, dict(dict(action="add", weekday=5, start_time="10:00", end_time="12:00"), **form))


def test_doctor_adds_a_shift_that_patients_can_book(site):
    assert "Shift added" in hours(site.doctor(2))
    saturday = date.today() + timedelta(days=(5 - date.today().weekday()) % 7 or 7)
    assert "Dr. Marcus Chen" in site.patient().page(f"/book?date={saturday}")


def test_shift_rules(site):
    doctor = site.doctor(2)
    hours(doctor)
    assert "overlaps" in hours(doctor, start_time="11:00", end_time="13:00")
    assert "half hour" in hours(doctor, start_time="12:15", end_time="13:00")
    assert "end after" in hours(doctor, start_time="14:00", end_time="13:00")


def test_shift_with_bookings_cannot_be_removed(site, monday):
    site.appointment(site.patient(1).user_id, 1, monday, "09:00")
    shift = site.one("SELECT id FROM doctor_schedules WHERE doctor_id = 1 AND weekday = 0")["id"]
    doctor = site.doctor(1)
    assert "fall in this shift" in doctor.text("/doctor/hours", dict(action="remove", shift_id=shift))
    site.sql("UPDATE appointments SET status = 'cancelled'")
    assert "Shift removed" in doctor.text("/doctor/hours", dict(action="remove", shift_id=shift))


def test_admin_manages_any_doctors_hours(site):
    admin = site.admin()
    page = admin.page("/admin/doctors")
    assert "No login yet" in page and "Edit hours" in page
    assert "Shift added" in hours(admin, "/admin/doctors/2/hours")


# ---------- Setup and demo data ----------
def test_old_database_explains_how_to_rebuild(tmp_path):
    from app import create_app
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE users (id INTEGER)")
    con.commit()
    con.close()
    r = create_app({"DATABASE": str(path), "TESTING": True}).test_client().get("/login")
    assert r.status_code == 500 and b"flask --app app init-db" in r.data


def test_seed_demo_loads_working_demo_accounts(app, site):
    result = app.test_cli_runner().invoke(args=["seed-demo"])
    assert "Demo data loaded" in result.output
    assert "Clinic summary" in site.browser().login("frontdesk@torontomu.ca")
    assert "Dr. Priya Raman" in site.browser().login("priya.raman@torontomu.ca")
    sam = site.browser("sam.lee@torontomu.ca")
    assert "You have 1 new message" in sam.page("/appointments") and "Wait lists you" in sam.page("/appointments")
    page = sam.page("/messages")
    assert "a spot opened up" in page and "Reminder: appointment tomorrow" in page
    assert site.one("SELECT COUNT(*) AS n FROM walk_ins")["n"] == 6
    assert site.one("SELECT COUNT(*) AS n FROM emails WHERE kind = 'walkin_near'")["n"] == 1  # Dan, #2 in line


def test_unknown_pages_show_a_friendly_404(site):
    r = site.patient().get("/no-such-page")
    assert r.status_code == 404 and b"Page not found" in r.data


def test_init_db_command_rebuilds_an_empty_database(app, site):
    site.patient(1)
    result = app.test_cli_runner().invoke(args=["init-db"])
    assert "Database created" in result.output
    assert site.one("SELECT COUNT(*) AS n FROM users")["n"] == 0
    assert site.one("SELECT COUNT(*) AS n FROM doctors")["n"] == 5
