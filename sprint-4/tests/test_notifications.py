"""Sprint 4 email notifications: day-before reminders, walk-ins who stepped out, appointment updates."""
from datetime import date, timedelta

from test_walkins import add, entry, works_today

TOMORROW = lambda: date.today() + timedelta(days=1)  # noqa: E731


def emails(site, kind=None):
    rows = site.sql("SELECT * FROM emails" + (" WHERE kind = ?" if kind else "") + " ORDER BY id", (kind,) if kind else ())
    return rows if isinstance(rows, list) else []


def run_reminders(site):
    with site.app.app_context():
        import reminders
        return reminders.send_due()


# ---------- Day-before reminders ----------
def test_reminder_goes_out_once_the_day_before(site):
    b = site.patient(1)
    appt = site.appointment(b.user_id, 1, TOMORROW(), "09:00")
    assert run_reminders(site) == 1
    assert run_reminders(site) == 0  # never twice
    [mail] = emails(site, "reminder")
    assert mail["to_address"] == "patient01@torontomu.ca" or mail["to_address"] == "patient1@torontomu.ca"
    assert "tomorrow" in mail["body"] and "09:00" in mail["body"] and "Dr. Priya Raman" in mail["body"]
    assert "/messages" in mail["body"]
    assert mail["status"] == "printed"  # no mail server in tests


def test_only_tomorrows_booked_appointments_get_reminders(site, monday):
    site.appointment(site.patient(1).user_id, 1, monday, "09:00")                    # later in the month
    site.appointment(site.patient(2).user_id, 1, TOMORROW(), "09:00", "cancelled")   # cancelled
    site.appointment(site.patient(3).user_id, 1, date.today(), "23:59")              # today
    assert run_reminders(site) == 0


def test_patient_and_staff_see_that_the_reminder_was_sent(site):
    b = site.patient(1)
    appt = site.appointment(b.user_id, 1, TOMORROW(), "09:00")
    assert "We'll email" in b.page(f"/appointments/{appt}")
    run_reminders(site)
    assert "Reminder emailed" in b.page("/appointments")
    assert "Emailed to" in b.page(f"/appointments/{appt}")
    assert "Reminder emailed" in site.admin().page(f"/admin/dashboard?date={TOMORROW()}")
    assert "Reminded" in site.doctor(1).page(f"/doctor/dashboard?date={TOMORROW()}")


def test_admin_can_send_tomorrows_reminders_from_the_dashboard(site):
    site.appointment(site.patient(1).user_id, 1, TOMORROW(), "09:00")
    admin = site.admin()
    page = admin.page("/admin/dashboard")
    assert "0 of 1 of tomorrow" in page and "Send now" in page
    assert "1 reminder email(s) sent" in admin.text("/admin/reminders/send", from_page="/admin/dashboard")
    assert "1 of 1 of tomorrow" in admin.page("/admin/dashboard")


def test_rescheduling_resets_the_reminder(site, monday):
    b = site.patient(1)
    appt = site.appointment(b.user_id, 1, monday, "09:00", reminder_sent_at="2026-01-01 09:00")
    b.text(f"/appointments/{appt}/reschedule", dict(date=monday.isoformat(), time="10:00"))
    assert site.one("SELECT reminder_sent_at FROM appointments")["reminder_sent_at"] is None


def test_send_reminders_command(app, site):
    site.appointment(site.patient(1).user_id, 1, TOMORROW(), "09:00")
    assert "1 reminder(s) sent" in app.test_cli_runner().invoke(args=["send-reminders"]).output


def test_mail_problems_never_break_a_page(app, site):
    app.config.update(MAIL_SERVER="127.0.0.1", MAIL_PORT=1)  # nothing listens here
    site.appointment(site.patient(1).user_id, 1, TOMORROW(), "09:00")
    assert run_reminders(site) == 0  # not marked sent, so it's retried later
    [mail] = emails(site)
    assert mail["status"] == "failed" and mail["error"]
    assert "Failed" in site.admin().page("/admin/emails")


# ---------- Patient message center ----------
def test_reminder_is_posted_to_the_message_center(site):
    b = site.patient(1)
    appt = site.appointment(b.user_id, 1, TOMORROW(), "09:00")
    assert 'class="badge"' not in b.page("/appointments")
    run_reminders(site)
    assert 'class="badge"' in b.page("/appointments")
    page = b.page("/messages")
    assert "Reminder: appointment tomorrow at 09:00" in page and "Dr. Priya Raman" in page
    assert "Emailed" in page and f"/appointments/{appt}" in page


def test_failed_email_still_posts_the_message_and_retries_only_the_email(app, site):
    b = site.patient(1)
    site.appointment(b.user_id, 1, TOMORROW(), "09:00")
    app.config.update(MAIL_SERVER="127.0.0.1", MAIL_PORT=1)
    run_reminders(site)
    assert "didn&#39;t go through" in b.page("/messages") or "didn't go through" in b.page("/messages")
    app.config.update(MAIL_SERVER=None)
    assert run_reminders(site) == 1
    notes = site.sql("SELECT * FROM notifications")
    assert len(notes) == 1 and notes[0]["email_status"] == "printed"  # one message, emailed on retry


def test_messages_are_private_and_only_for_patients(site):
    site.appointment(site.patient(1).user_id, 1, TOMORROW(), "09:00")
    run_reminders(site)
    assert "No messages yet" in site.patient(2).page("/messages")
    assert site.admin().get("/messages").status_code == 403
    assert site.doctor().get("/messages").status_code == 403


# ---------- Walk-ins who stepped out ----------
def test_stepped_out_walk_in_needs_an_email(site):
    page = add(site.admin(), stepped_out="1")
    assert "Add an email address" in page


def test_account_email_is_used_when_none_is_typed(site):
    site.patient(1)
    add(site.admin(), student_id="500000001", stepped_out="1")
    assert entry(site, "Alex Kim")["email"] == "patient1@torontomu.ca"


def test_stepped_out_walk_in_is_emailed_when_two_people_are_ahead(site):
    works_today(site, 1)
    desk = site.admin()
    for name in ("A One", "B Two", "C Three"):
        add(desk, patient_name=name)
    add(desk, patient_name="Dan Wu", email="dan@example.com", stepped_out="1")  # #4: 3 ahead, no email yet
    assert emails(site, "walkin_near") == []
    page = desk.page("/walk-ins/")
    assert "Stepped out" in page and "Will be emailed at dan@example.com" in page
    site.doctor(1).text("/doctor/walk-ins/call-next", from_page="/doctor/dashboard")  # A goes in, Dan is #3
    [mail] = emails(site, "walkin_near")
    assert mail["to_address"] == "dan@example.com" and "2 people ahead of you" in mail["body"]
    assert "Emailed &#34;your turn is coming&#34;" in desk.page("/walk-ins/") or "Emailed \"your turn is coming\"" in desk.page("/walk-ins/")
    desk.text(f"/walk-ins/{entry(site, 'B Two')['id']}/status", dict(status="left"), from_page="/walk-ins/")
    assert len(emails(site, "walkin_near")) == 1  # only once


def test_walk_in_who_steps_out_near_the_front_is_emailed_right_away(site):
    desk = site.admin()
    add(desk, patient_name="A One")
    add(desk, patient_name="Dan Wu", email="dan@example.com")
    assert emails(site, "walkin_near") == []  # still in the waiting room
    desk.text(f"/walk-ins/{entry(site, 'Dan Wu')['id']}/stepped-out", dict(stepped_out="1"), from_page="/walk-ins/")
    [mail] = emails(site, "walkin_near")
    assert "1 person ahead of you" in mail["body"]


def test_stepped_out_walk_in_is_emailed_when_called(site):
    works_today(site, 1)
    desk = site.admin()
    add(desk, patient_name="Dan Wu", email="dan@example.com", stepped_out="1")
    assert "You&#39;re next" in emails(site, "walkin_near")[0]["body"] or "You're next" in emails(site, "walkin_near")[0]["body"]
    site.doctor(1).text("/doctor/walk-ins/call-next", from_page="/doctor/dashboard")
    [mail] = emails(site, "walkin_called")
    assert "It's your turn" in mail["body"] and "Dr. Priya Raman" in mail["body"]
    assert "your turn&#34; at" in desk.page("/walk-ins/") or "your turn\" at" in desk.page("/walk-ins/")


def test_walk_ins_in_the_waiting_room_get_no_emails(site):
    works_today(site, 1)
    add(site.admin(), email="dan@example.com")
    site.doctor(1).text("/doctor/walk-ins/call-next", from_page="/doctor/dashboard")
    assert emails(site) == []


def test_marking_someone_back_in_the_room_stops_emails(site):
    works_today(site, 1)
    desk = site.admin()
    for name in ("A One", "B Two", "C Three"):
        add(desk, patient_name=name)
    add(desk, patient_name="Dan Wu", email="dan@example.com", stepped_out="1")
    desk.text(f"/walk-ins/{entry(site, 'Dan Wu')['id']}/stepped-out", dict(stepped_out="0"), from_page="/walk-ins/")
    site.doctor(1).text("/doctor/walk-ins/call-next", from_page="/doctor/dashboard")
    assert emails(site, "walkin_near") == []


# ---------- Appointment updates also go by email ----------
def test_wait_list_booking_and_clinic_cancellation_are_emailed(site, monday):
    doctor = site.new_doctor(slots_on=monday, start="09:00", end="09:30")
    first = site.patient(1)
    site.appointment(site.patient(2).user_id, doctor, monday, "09:00")
    first.text("/waitlist", dict(doctor_id=doctor, date=monday.isoformat()), from_page="/appointments")
    appt = site.one("SELECT id FROM appointments")["id"]
    site.admin().text(f"/admin/appointments/{appt}/cancel", from_page=f"/admin/dashboard?date={monday}")
    subjects = {m["to_address"]: m["subject"] for m in emails(site, "notification")}
    assert subjects["patient2@torontomu.ca"] == "Your appointment was cancelled"
    assert subjects["patient1@torontomu.ca"].startswith("You're booked")


def test_only_admins_see_the_email_log(site):
    assert site.patient().get("/admin/emails").status_code == 403
    assert "Emails sent" in site.admin().page("/admin/emails")
