import os, re, sys, tempfile
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import create_app
tmp = tempfile.mkdtemp()
app = create_app({"DATABASE": os.path.join(tmp, "t.db"), "TESTING": True})
# re-init for new DB path
import db


def tok(c, path):
    html = c.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)

def post(c, path, data, page=None, follow=True):
    data = dict(data, csrf=tok(c, page or path))
    return c.post(path, data=data, follow_redirects=follow)

d = date.today() + timedelta(days=1)
while d.weekday() != 0: d += timedelta(days=1)   # next Monday (Dr. Raman 9-12, Dr. Bello 13-17)

c = app.test_client()
r = post(c, "/register", dict(full_name="A", email="a@gmail.com", student_id="123", password="short", confirm="x"))
t = r.get_data(as_text=True); assert "@torontomu.ca" in t and "9 digits" in t and "8 characters" in t; print("validation ok")
r = post(c, "/register", dict(full_name="Sam Lee", email="sam.lee@torontomu.ca", student_id="501234567", password="password123", confirm="password123"))
assert "Account created" in r.get_data(as_text=True)
r = post(c, "/register", dict(full_name="Sam Lee", email="sam.lee@torontomu.ca", student_id="501234567", password="password123", confirm="password123"))
assert "already exists" in r.get_data(as_text=True); print("register ok")
r = post(c, "/login", dict(email="sam.lee@torontomu.ca", password="wrongpass"))
assert "incorrect" in r.get_data(as_text=True)
r = post(c, "/login", dict(email="SAM.LEE@torontomu.ca", password="password123"))
assert "My appointments" in r.get_data(as_text=True); print("login ok")
assert c.get("/admin/dashboard").status_code == 403; print("role block ok")
page = c.get(f"/book?date={d}").get_data(as_text=True)
assert "Dr. Priya Raman" in page and "09:00" in page and "Dr. Marcus Chen" not in page
r = post(c, "/book", dict(doctor_id=1, date=d.isoformat(), time="09:00", reason="Checkup"), page=f"/book?date={d}")
assert "Booked with Dr. Priya Raman" in r.get_data(as_text=True)
page = c.get(f"/book?date={d}&specialty=General+Practice").get_data(as_text=True)
assert 'value="09:00"' not in page and "Dr. Aisha Bello" not in page; print("book + filter ok")
r = post(c, "/book", dict(doctor_id=1, date=d.isoformat(), time="09:07"), page="/book")
assert "available. Choose another slot" in r.get_data(as_text=True); print("bad slot ok")
# no csrf
assert c.post("/book", data=dict(doctor_id=1, date=d.isoformat(), time="09:30")).status_code == 400; print("csrf ok")

c2 = app.test_client()
post(c2, "/register", dict(full_name="Jo Park", email="jo@torontomu.ca", student_id="501111111", password="password123", confirm="password123"))
post(c2, "/login", dict(email="jo@torontomu.ca", password="password123"))
r = post(c2, "/book", dict(doctor_id=1, date=d.isoformat(), time="09:00"), page="/book")
assert "available. Choose another slot" in r.get_data(as_text=True) or "just booked" in r.get_data(as_text=True)
r = post(c2, "/book", dict(doctor_id=3, date=d.isoformat(), time="13:30"), page="/book")
assert "Booked" in r.get_data(as_text=True); print("double-book blocked ok")
# cancel
appts = c2.get("/appointments").get_data(as_text=True)
aid = re.search(r'/appointments/(\d+)/cancel', appts).group(1)
assert c.post(f"/appointments/{aid}/cancel", data={"csrf": tok(c, "/appointments")}, follow_redirects=True).get_data(as_text=True).count("be cancelled.") == 1
r = post(c2, f"/appointments/{aid}/cancel", {}, page="/appointments")
assert "Appointment cancelled" in r.get_data(as_text=True); print("cancel ok (and others can't cancel)")

a = app.test_client()
r = post(a, "/admin/register", dict(full_name="Admin", email="clinic.admin@torontomu.ca", invite_code="nope", password="adminpass1", confirm="adminpass1"))
assert "invite code is incorrect" in r.get_data(as_text=True)
post(a, "/admin/register", dict(full_name="Clinic Admin", email="clinic.admin@torontomu.ca", invite_code="TMU-STAFF-2026", password="adminpass1", confirm="adminpass1"))
r = post(a, "/login", dict(email="clinic.admin@torontomu.ca", password="adminpass1"))
assert "Clinic summary" in r.get_data(as_text=True)
assert a.get("/book").status_code == 403
dash = a.get(f"/admin/dashboard?date={d}").get_data(as_text=True)
assert "Sam Lee" in dash and "Jo Park" in dash and "Cancelled" in dash
assert re.search(r"<dd>1<small> of 14 slots", dash), re.findall(r"<dd>.*?</dd>", dash)
print("admin ok")

# ---------- Full admin dashboard ----------
import sqlite3
for path in ("/admin/doctors", "/admin/doctors/1", "/admin/patients?q=a", "/admin/patients/1", "/admin/reports", "/admin/book?patient_id=1"):
    assert c.get(path).status_code == 403, path
print("admin routes blocked for patients ok")

def appt_ids(html):
    return re.findall(r'/admin/appointments/(\d+)/status', html)

# A future booking can be cancelled but not marked completed
sam_appt = appt_ids(dash)[0]
r = post(a, f"/admin/appointments/{sam_appt}/status", dict(status="completed"), page=f"/admin/dashboard?date={d}")
assert "once its start time has passed" in r.get_data(as_text=True)
assert a.post(f"/admin/appointments/{sam_appt}/status", data=dict(status="cancelled")).status_code == 400  # no csrf

# A past booking can be marked completed, then not cancelled
y = date.today() - timedelta(days=1)
con = sqlite3.connect(app.config["DATABASE"])
sam_id = con.execute("SELECT id FROM users WHERE email = 'sam.lee@torontomu.ca'").fetchone()[0]
con.execute("INSERT INTO appointments (patient_id, doctor_id, appt_date, start_time) VALUES (?, 1, ?, '09:00')", (sam_id, y.isoformat()))
con.commit(); con.close()
past = a.get(f"/admin/dashboard?date={y}").get_data(as_text=True)
assert "No-show" in past
past_appt = appt_ids(past)[0]
r = post(a, f"/admin/appointments/{past_appt}/status", dict(status="completed"), page=f"/admin/dashboard?date={y}")
assert "marked completed" in r.get_data(as_text=True)
r = post(a, f"/admin/appointments/{past_appt}/status", dict(status="cancelled"), page=f"/admin/dashboard?date={y}")
assert "already started" in r.get_data(as_text=True); print("appointment status ok")

# Schedule changes that would strand Sam's booking are refused
edit = a.get("/admin/doctors/1").get_data(as_text=True)
monday_shift = re.findall(r'/admin/shifts/(\d+)/delete', edit)[0]
r = post(a, f"/admin/shifts/{monday_shift}/delete", {}, page="/admin/doctors/1")
assert "Can&#39;t remove this shift" in r.get_data(as_text=True)
r = post(a, "/admin/doctors/1/time-off", dict(off_date=d.isoformat()), page="/admin/doctors/1")
assert "Can&#39;t add time off" in r.get_data(as_text=True)
r = post(a, "/admin/doctors/1/active", {}, page="/admin/doctors/1")
assert "Can&#39;t deactivate" in r.get_data(as_text=True); print("stranding blocked ok")

# Admin cancels Sam's booking: the slot reopens, then time off hides the doctor
r = post(a, f"/admin/appointments/{sam_appt}/status", dict(status="cancelled"), page=f"/admin/dashboard?date={d}")
assert "Give the patient a reason" in r.get_data(as_text=True)
r = post(a, f"/admin/appointments/{sam_appt}/status", dict(status="cancelled", reason="Doctor at a conference"), page=f"/admin/dashboard?date={d}")
assert "09:00 cancelled" in r.get_data(as_text=True)
assert 'value="09:00"' in c.get(f"/book?date={d}&specialty=General+Practice").get_data(as_text=True)
r = post(a, "/admin/doctors/1/time-off", dict(off_date=d.isoformat(), reason="Conference"), page="/admin/doctors/1")
assert "as time off" in r.get_data(as_text=True)
assert "Dr. Priya Raman" not in c.get(f"/book?date={d}").get_data(as_text=True); print("cancel + time off ok")

# Add a doctor and a shift; patients can see it
form = a.get("/admin/doctors").get_data(as_text=True)
assert 'value="__new__"' in form and "<option >General Practice</option>" in form.replace("<option>", "<option >")
r = post(a, "/admin/doctors", dict(full_name="Dr. Test Person", specialty="__new__", specialty_new="  Dermatology ", department="Primary Care"), page="/admin/doctors")
assert "Added Dr. Test Person" in r.get_data(as_text=True)
new_id = re.search(r"/admin/doctors/(\d+)", r.request.path).group(1)
page = f"/admin/doctors/{new_id}"
assert "on the hour or half hour" in post(a, f"{page}/shifts", dict(weekday=0, start_time="08:15", end_time="09:00"), page=page).get_data(as_text=True)
assert "Added Monday 08:00" in post(a, f"{page}/shifts", dict(weekday=0, start_time="08:00", end_time="09:00"), page=page).get_data(as_text=True)
assert "overlaps" in post(a, f"{page}/shifts", dict(weekday=0, start_time="08:30", end_time="10:00"), page=page).get_data(as_text=True)
avail = c.get(f"/book?date={d}&specialty=Dermatology").get_data(as_text=True)
assert "Dr. Test Person" in avail and 'value="08:30"' in avail; r = post(a, "/admin/doctors", dict(full_name="Dr. Case Check", specialty="__new__", specialty_new="general practice", department="__new__", department_new=""), page="/admin/doctors")
assert "Enter the doctor&#39;s department" in r.get_data(as_text=True)
r = post(a, "/admin/doctors", dict(full_name="Dr. Case Check", specialty="__new__", specialty_new="general practice", department="__new__", department_new="Walk-in Clinic"), page="/admin/doctors")
con = sqlite3.connect(app.config["DATABASE"])
assert con.execute("SELECT specialty, department FROM doctors WHERE full_name = 'Dr. Case Check'").fetchone() == ("General Practice", "Walk-in Clinic")
con.close()
assert "<option selected>Walk-in Clinic</option>" in r.get_data(as_text=True)
print("doctors + shifts ok (addable dropdowns)")

# Find a patient and book on their behalf
found = a.get("/admin/patients?q=501111111").get_data(as_text=True)
assert "Jo Park" in found and "Sam Lee" not in found
jo = re.search(r"/admin/patients/(\d+)", found).group(1)
r = post(a, "/admin/book", dict(patient_id=jo, doctor_id=new_id, date=d.isoformat(), time="08:30", reason="Rash"), page=f"/admin/book?patient_id={jo}")
assert "Booked Jo Park" in r.get_data(as_text=True)
assert "08:30" in c2.get("/appointments").get_data(as_text=True)
history = a.get(f"/admin/patients/{jo}").get_data(as_text=True)
assert "Dr. Test Person" in history and "Cancelled" in history; print("patients + staff booking ok")

# Report: Sam's completed visit, Jo's staff booking, two cancellations
rep = a.get(f"/admin/reports?start={y}&end={d}").get_data(as_text=True)
assert re.search(r"<dt>Completed</dt><dd>1</dd>", rep) and re.search(r"<dt>Cancellations</dt><dd>2</dd>", rep), re.findall(r"<dd>.*?</dd>", rep)
assert "Dermatology" in rep; print("reports ok")

# ---------- Doctor accounts ----------
def invite_path(html):
    m = re.search(r'value="https?://[^"/]+(/doctor/join/[^"]+)"', html)
    return m.group(1) if m else None

chen = "/admin/doctors/2"
assert "No account" in a.get("/admin/doctors").get_data(as_text=True)
r = post(a, f"{chen}/invite", dict(email="marcus@gmail.com"), page=chen)
assert "@torontomu.ca" in r.get_data(as_text=True) and invite_path(r.get_data(as_text=True)) is None
r = post(a, f"{chen}/invite", dict(email="sam.lee@torontomu.ca"), page=chen)
assert "already belongs to another account" in r.get_data(as_text=True)
r = post(a, f"{chen}/invite", dict(email="marcus.chen@torontomu.ca"), page=chen)
old_link = invite_path(r.get_data(as_text=True))
assert old_link and "Invite pending" in r.get_data(as_text=True)
assert invite_path(a.get(chen).get_data(as_text=True)) is None  # link is only shown once
r = post(a, f"{chen}/invite", dict(email="marcus.chen@torontomu.ca"), page=chen)
link = invite_path(r.get_data(as_text=True))
doc = app.test_client()
assert doc.get(old_link).status_code == 404; print("invite ok (old link replaced)")

page = doc.get(link).get_data(as_text=True)
assert "Dr. Marcus Chen" in page and "marcus.chen@torontomu.ca" in page
r = post(doc, link, dict(password="short", confirm="short"))
assert "8 characters" in r.get_data(as_text=True)
r = post(doc, link, dict(password="doctorpass2", confirm="doctorpass2"))
assert "Account created" in r.get_data(as_text=True)
assert doc.get(link).status_code == 404
assert "Active login" in a.get(chen).get_data(as_text=True); print("doctor sign-up ok")

r = post(doc, "/login", dict(email="marcus.chen@torontomu.ca", password="doctorpass2"))
t = r.get_data(as_text=True)
assert "Welcome, Dr. Marcus Chen" in t and "Your schedule" in t and "Change password" in t
assert doc.get("/admin/dashboard").status_code == 403 and doc.get("/book").status_code == 403
assert c.get("/doctor/home").status_code == 403 and a.get("/doctor/home").status_code == 403
assert doc.post("/account/password", data=dict(current="doctorpass2", password="x" * 9, confirm="x" * 9)).status_code == 400  # csrf
print("doctor login + roles ok")

r = post(doc, "/account/password", dict(current="wrongpass", password="doctorpass3", confirm="doctorpass3"))
assert "Current password is incorrect" in r.get_data(as_text=True)
r = post(doc, "/account/password", dict(current="doctorpass2", password="doctorpass3", confirm="doctorpass3"))
assert "Password changed" in r.get_data(as_text=True)
d2 = app.test_client()
assert "incorrect" in post(d2, "/login", dict(email="marcus.chen@torontomu.ca", password="doctorpass2")).get_data(as_text=True)
assert "Welcome" in post(d2, "/login", dict(email="marcus.chen@torontomu.ca", password="doctorpass3")).get_data(as_text=True)
print("change password ok")

# Deactivating blocks login and ends open sessions; reactivating restores it
r = post(a, f"{chen}/active", {}, page=chen)
assert "can&#39;t log in" in r.get_data(as_text=True) and "Login disabled" in r.get_data(as_text=True)
assert doc.get("/doctor/home", follow_redirects=True).request.path == "/login"
d3 = app.test_client()
assert "disabled" in post(d3, "/login", dict(email="marcus.chen@torontomu.ca", password="doctorpass3")).get_data(as_text=True)
post(a, f"{chen}/active", {}, page=chen)
assert "Welcome" in post(d3, "/login", dict(email="marcus.chen@torontomu.ca", password="doctorpass3")).get_data(as_text=True)
print("deactivate blocks login ok")

# Expired invites don't work; renaming a doctor renames their login
r = post(a, "/admin/doctors/3/invite", dict(email="aisha.bello@torontomu.ca"), page="/admin/doctors/3")
expired = invite_path(r.get_data(as_text=True))
con = sqlite3.connect(app.config["DATABASE"])
con.execute("UPDATE doctor_invites SET expires_at = '2000-01-01 00:00:00' WHERE doctor_id = 3")
con.commit(); con.close()
assert app.test_client().get(expired).status_code == 404
assert "Invite expired" in a.get("/admin/doctors/3").get_data(as_text=True)
post(a, chen, dict(full_name="Dr. Marcus Chen-Li", specialty="General Practice", department="Primary Care"), page=chen)
assert "Dr. Marcus Chen-Li" in d3.get("/doctor/home").get_data(as_text=True)
print("expired invite + rename ok")

demo = app.test_client()
assert "Welcome, Dr. Priya Raman" in post(demo, "/login", dict(email="priya.raman@torontomu.ca", password="doctorpass1")).get_data(as_text=True)
print("demo doctor ok")

# ---------- Doctor dashboard (demo doctor = Dr. Priya Raman, doctor 1) ----------
today = date.today()
wed = d + timedelta(days=2)  # Dr. Raman works Wednesday 09:00-12:00
con = sqlite3.connect(app.config["DATABASE"])
jo_id = con.execute("SELECT id FROM users WHERE email = 'jo@torontomu.ca'").fetchone()[0]
other = con.execute("SELECT id FROM appointments WHERE patient_id = ? AND doctor_id = ?", (jo_id, new_id)).fetchone()[0]
now_appt = con.execute("INSERT INTO appointments (patient_id, doctor_id, appt_date, start_time, reason) VALUES (?, 1, ?, '00:00', 'Sore throat')",
                       (sam_id, today.isoformat())).lastrowid
old_appt = con.execute("INSERT INTO appointments (patient_id, doctor_id, appt_date, start_time, status) VALUES (?, 1, ?, '09:00', 'completed')",
                       (sam_id, (today - timedelta(days=10)).isoformat())).lastrowid
con.commit(); con.close()

for path in ("/doctor/home", "/doctor/schedule", f"/doctor/appointments/{now_appt}", f"/doctor/patients/{sam_id}"):
    assert c.get(path).status_code == 403 and a.get(path).status_code == 403, path
assert demo.get(f"/doctor/appointments/{other}").status_code == 404
assert demo.get(f"/doctor/patients/{jo_id}").status_code == 404  # Jo hasn't booked with Dr. Raman yet
assert demo.post(f"/doctor/appointments/{other}/status", data=dict(status="completed", csrf=tok(demo, "/doctor/home"))).status_code == 404
assert demo.post(f"/doctor/appointments/{now_appt}/status", data=dict(status="completed")).status_code == 400  # csrf
print("doctor access rules ok")

# Day view: own patients, open slots, time off, cancelled with reason
post(c2, "/book", dict(doctor_id=1, date=wed.isoformat(), time="09:30", reason="Follow-up"), page=f"/book?date={wed}")
future = re.search(r"/doctor/appointments/(\d+)", demo.get(f"/doctor/home?date={wed}").get_data(as_text=True)).group(1)
day = demo.get(f"/doctor/home?date={wed}").get_data(as_text=True)
assert "Jo Park" in day and "Open" in day and "Sam Lee" not in day
assert re.search(r"<dt>Booked</dt><dd>1</dd>", day) and re.search(r"<dt>Open slots</dt><dd>5</dd>", day)
away = demo.get(f"/doctor/home?date={d}").get_data(as_text=True)
assert "marked as away" in away and "Doctor at a conference" in away and "Dr. Test Person" not in away
assert "Jo Park" in demo.get(f"/doctor/patients/{jo_id}").get_data(as_text=True)
print("doctor day view ok")

# Status rules
def doc_status(appt, **data):
    return post(demo, f"/doctor/appointments/{appt}/status", data, page="/doctor/home").get_data(as_text=True)

assert "once its start time has passed" in doc_status(future, status="completed")
assert "Give the patient a reason" in doc_status(future, status="cancelled")
assert "Give the patient a reason" in doc_status(future, status="cancelled", reason="  ")

# Notes open only once the visit is completed; the patient sees only the shared note
visit = f"/doctor/appointments/{now_appt}"
assert "Notes can only be written" in post(demo, visit, dict(private_note="x", shared_note="y")).get_data(as_text=True)
assert "marked completed" in doc_status(now_appt, status="completed")
assert f'/doctor/appointments/{now_appt}">Add notes' in demo.get("/doctor/home").get_data(as_text=True)
assert "Notes saved" in post(demo, visit, dict(private_note="Private thoughts xyz", shared_note="Drink water abc")).get_data(as_text=True)
mine = c.get(f"/appointments/{now_appt}").get_data(as_text=True)
assert "Drink water abc" in mine and "Private thoughts xyz" not in mine
assert c2.get(f"/appointments/{now_appt}").status_code == 404
assert f'/doctor/appointments/{now_appt}">View visit' in demo.get("/doctor/home").get_data(as_text=True)
admin_day = a.get(f"/admin/dashboard?date={today}").get_data(as_text=True)
assert 'tag note">Note' in admin_day and "Drink water abc" not in admin_day and "Private thoughts xyz" not in admin_day
print("visit notes ok")

# Undo: doctors only, and only on the day of the visit
assert "can&#39;t be set back" in post(a, f"/admin/appointments/{now_appt}/status", dict(status="booked"), page="/admin/dashboard").get_data(as_text=True)
assert "set back to booked" in doc_status(now_appt, status="booked")
assert "Drink water abc" not in c.get(f"/appointments/{now_appt}").get_data(as_text=True)  # hidden while booked
assert "marked completed" in doc_status(now_appt, status="completed")
assert "Drink water abc" in c.get(f"/appointments/{now_appt}").get_data(as_text=True)
assert "on the day of the visit" in doc_status(past_appt, status="booked")
print("undo ok")

# Notes lock 7 days after the visit
locked = demo.get(f"/doctor/appointments/{old_appt}").get_data(as_text=True)
assert "Locked on" in locked and "<textarea" not in locked
assert "Notes can only be written" in post(demo, f"/doctor/appointments/{old_appt}", dict(private_note="late")).get_data(as_text=True)
print("note lock ok")

# Clinic cancel with a reason is shown to the patient
assert "cancelled" in doc_status(future, status="cancelled", reason="Doctor is unwell")
assert "Cancelled by the clinic: Doctor is unwell" in c2.get("/appointments").get_data(as_text=True)
assert "Cancelled by the clinic: Doctor is unwell" in c2.get(f"/appointments/{future}").get_data(as_text=True)
print("doctor cancel ok")

# Own schedule is read-only; 30-day stats match the admin report
sched = demo.get("/doctor/schedule").get_data(as_text=True)
assert "Monday</strong> 09:00–12:00" in sched and d.isoformat() in sched and "Remove" not in sched
home = demo.get("/doctor/home").get_data(as_text=True)
used, capacity = re.search(r"<dt>Slots filled</dt><dd>\d+%<small> (\d+) of (\d+)</small>", home).groups()
rep = a.get(f"/admin/reports?start={today - timedelta(days=29)}&end={today}").get_data(as_text=True)
row = re.search(r"Dr\. Priya Raman<br>.*?<td class=\"num\">(\d+)</td>\s*<td class=\"num\">(\d+) <small>", rep, re.S)
assert row and row.groups() == (capacity, used), (row and row.groups(), capacity, used)
print("doctor schedule + stats ok")


# ---------- Walk-ins, kiosk check-in, arrival and late release ----------
import time
from datetime import datetime
from werkzeug.security import generate_password_hash

def flash_text(html):
    return " ".join(re.findall(r'<p class="flash \w+">(.*?)</p>', html))

def hm(t):
    return t.strftime("%H:%M")

now = datetime.now()
if (30 - now.minute % 30) * 60 - now.second < 90:  # don't straddle a slot boundary mid-test
    time.sleep((30 - now.minute % 30) * 60 - now.second + 2)
    now = datetime.now()
s0 = now.replace(minute=now.minute - now.minute % 30, second=0, microsecond=0)   # slot running now
if not (s0.hour >= 1 and s0 + timedelta(minutes=120) <= s0.replace(hour=23, minute=59)):
    print("walk-in tests skipped: run them between 01:00 and 21:30")
else:
    p1, cur, f1, f2 = (hm(s0 + timedelta(minutes=m)) for m in (-30, 0, 30, 60))
    con = sqlite3.connect(app.config["DATABASE"])
    w = {}
    for n in (1, 2):  # two doctors in a test-only specialty, working an hour before to two hours after now
        uid = con.execute("INSERT INTO users (full_name, email, password_hash, role) VALUES (?, ?, ?, 'doctor')",
                          (f"Dr. Walk {n}", f"walk{n}@torontomu.ca", generate_password_hash("walkpass1"))).lastrowid
        w[n] = con.execute("INSERT INTO doctors (full_name, specialty, department, user_id) VALUES (?, 'Walk-in Clinic', 'Primary Care', ?)",
                           (f"Dr. Walk {n}", uid)).lastrowid
        con.execute("INSERT INTO doctor_schedules (doctor_id, weekday, start_time, end_time) VALUES (?, ?, ?, ?)",
                    (w[n], today.weekday(), hm(s0 - timedelta(minutes=60)), hm(s0 + timedelta(minutes=120))))
    def booking(patient, doc, t):
        return con.execute("INSERT INTO appointments (patient_id, doctor_id, appt_date, start_time) VALUES (?, ?, ?, ?)",
                           (patient, w[doc], today.isoformat(), t)).lastrowid
    sam_late = booking(sam_id, 1, p1)    # 30+ minutes late, not arrived
    jo_now = booking(jo_id, 1, cur)      # Dr. Walk 1's current slot is taken
    sam_later = booking(sam_id, 2, f1)   # future
    jo_later = booking(jo_id, 2, f2)
    con.commit(); con.close()
    # Free slots left today: Dr. Walk 1 at f1, f2, f3; Dr. Walk 2 at cur, f3 -> 5

    def login(email, password):
        cl = app.test_client(); post(cl, "/login", dict(email=email, password=password)); return cl
    k = login("kiosk@torontomu.ca", "kioskpass1")
    w1, w2 = login("walk1@torontomu.ca", "walkpass1"), login("walk2@torontomu.ca", "walkpass1")
    assert "Clinic check-in" in k.get("/").get_data(as_text=True) or "Clinic check-in" in k.get("/kiosk").get_data(as_text=True)
    assert k.get("/", follow_redirects=True).request.path == "/kiosk"
    for path in ("/admin/dashboard", "/admin/walk-ins", "/doctor/home", "/book", "/appointments"):
        assert k.get(path).status_code == 403, path
    for cl in (c, a, demo):
        assert cl.get("/kiosk").status_code == 403
    assert k.post("/kiosk/walk-in", data=dict(full_name="X")).status_code == 400  # csrf
    print("kiosk access ok")

    def walk_in(name, sid, email, specialty="Walk-in Clinic"):
        return flash_text(post(k, "/kiosk/walk-in", dict(full_name=name, student_id=sid, email=email,
                                                         specialty=specialty, reason="Cough"), page="/kiosk").get_data(as_text=True))
    ok_msg = r"You&#39;re #\d+ in line for Walk-in Clinic; (you should be seen shortly|your estimated time is \d\d:\d\d)\. Please take a seat\."
    m_sam = walk_in("Sam Lee", "501234567", "sam.lee@torontomu.ca")          # matches Sam's account
    m_guest = walk_in("Jo Park", "501111111", "jo.wrong@torontomu.ca")       # Jo's number, wrong email -> guest
    assert re.fullmatch(ok_msg, m_sam) and re.fullmatch(ok_msg, m_guest), (m_sam, m_guest)
    assert "already in the queue" in walk_in("Sam Lee", "501234567", "sam.lee@torontomu.ca")
    bad = walk_in("", "12", "x@gmail.com")
    assert "full name" in bad and "9 digits" in bad and "@torontomu.ca" in bad
    assert "open for walk-ins" in walk_in("Sam Lee", "501234567", "sam.lee@torontomu.ca", specialty="Nope")
    con = sqlite3.connect(app.config["DATABASE"])
    people = con.execute("SELECT u.role, u.email, u.guest_email FROM walk_ins w JOIN users u ON u.id = w.user_id ORDER BY w.id").fetchall()
    con.close()
    assert people == [("patient", "sam.lee@torontomu.ca", None), ("guest", None, "jo.wrong@torontomu.ca")], people
    print("kiosk walk-in identity ok")

    for i in range(3, 6):
        assert re.fullmatch(ok_msg, walk_in(f"Guest {i}", f"50{i}{i}{i}{i}{i}{i}{i}", f"g{i}@torontomu.ca"))
    assert "No walk-in spots left today for Walk-in Clinic" in walk_in("Guest 6", "506666666", "g6@torontomu.ca")
    qpage = a.get("/admin/walk-ins").get_data(as_text=True)
    estimates = re.findall(r'<td class="num">\d+ min</td>\s*<td>([^<]+)</td>', qpage)
    f3 = hm(s0 + timedelta(minutes=90))
    assert estimates == ["now", f1, f2, f3, f3], estimates   # Dr. Walk 2 now, then Dr. Walk 1 f1, f2, then both at f3
    print("capacity + estimates ok")

    # Call next: only into a free current slot, first come first served
    assert "already has a patient" in w1.get("/doctor/home").get_data(as_text=True)
    assert "already has a patient" in flash_text(post(w1, "/doctor/call-next", {}, page="/doctor/home").get_data(as_text=True))
    assert ">Call next</button>" in w2.get("/doctor/home").get_data(as_text=True)
    assert "Sam Lee has been called" in flash_text(post(w2, "/doctor/call-next", {}, page="/doctor/home").get_data(as_text=True))
    con = sqlite3.connect(app.config["DATABASE"])
    sam_walk, src, arrived = con.execute("SELECT id, source, arrived_at FROM appointments WHERE doctor_id = ? AND start_time = ? AND appt_date = ?",
                                         (w[2], cur, today.isoformat())).fetchone()
    con.close()
    assert src == "walk_in" and arrived
    r = post(w2, f"/doctor/appointments/{sam_walk}/status", dict(status="completed"), page="/doctor/home")
    assert "marked completed" in r.get_data(as_text=True)
    assert "already has a patient" in flash_text(post(w2, "/doctor/call-next", {}, page="/doctor/home").get_data(as_text=True))
    print("call next ok")

    # Late release: not before the grace period, not once arrived, then the slot can be called into
    r = flash_text(post(w2, f"/doctor/appointments/{sam_later}/release", {}, page="/doctor/home").get_data(as_text=True))
    assert "can be released from" in r, r
    assert w1.post(f"/doctor/appointments/{sam_later}/release", data=dict(csrf=tok(w1, "/doctor/home"))).status_code == 404
    assert "marked a no-show" in flash_text(post(w1, f"/doctor/appointments/{sam_late}/release", {}, page="/doctor/home").get_data(as_text=True))
    assert "Late; slot released" in w1.get("/doctor/home").get_data(as_text=True)
    app.config["LATE_GRACE_MINUTES"] = 0
    assert "marked a no-show" in flash_text(post(w1, f"/doctor/appointments/{jo_now}/release", {}, page="/doctor/home").get_data(as_text=True))
    assert "Jo Park has been called" in flash_text(post(w1, "/doctor/call-next", {}, page="/doctor/home").get_data(as_text=True))  # the guest, next in line
    r = post(w1, f"/doctor/appointments/{jo_now}/status", dict(status="booked"), page="/doctor/home")
    assert "given to a walk-in" in r.get_data(as_text=True)
    print("late release ok")

    # Arrival: kiosk (needs both details) and staff
    def arrive(sid, email):
        return flash_text(post(k, "/kiosk/arrive", dict(student_id=sid, email=email), page="/kiosk").get_data(as_text=True))
    assert "couldn&#39;t find a booking" in arrive("501234567", "jo@torontomu.ca")
    assert f"checked in for {f1} with Dr. Walk 2" in arrive("501234567", "sam.lee@torontomu.ca")
    assert f"already checked in for {f1}" in arrive("501234567", "sam.lee@torontomu.ca")
    assert "has checked in" in flash_text(post(w2, f"/doctor/appointments/{sam_later}/release", {}, page="/doctor/home").get_data(as_text=True))
    app.config["LATE_GRACE_MINUTES"] = 10
    assert "Checked in the" in flash_text(post(a, f"/admin/appointments/{jo_later}/arrive", {}, page="/admin/dashboard").get_data(as_text=True))
    assert "already checked in" in flash_text(post(a, f"/admin/appointments/{jo_later}/arrive", {}, page="/admin/dashboard").get_data(as_text=True))
    assert 'tag completed">Arrived' in a.get("/admin/dashboard").get_data(as_text=True)
    print("arrival ok")

    # Admin queue actions
    qpage = a.get("/admin/walk-ins").get_data(as_text=True)
    ids = re.findall(r"/admin/walk-ins/(\d+)/assign", qpage)
    assert len(ids) == 3 and "Guest 3" in qpage
    r = flash_text(post(a, f"/admin/walk-ins/{ids[0]}/assign", dict(doctor_id=w[1]), page="/admin/walk-ins").get_data(as_text=True))
    assert f"Guest 3 is booked with Dr. Walk 1 at {f1}" in r, r
    assert "left without being seen" in flash_text(post(a, f"/admin/walk-ins/{ids[1]}/end", dict(status="left"), page="/admin/walk-ins").get_data(as_text=True))
    assert "Give a reason" in flash_text(post(a, f"/admin/walk-ins/{ids[2]}/end", dict(status="removed", reason=""), page="/admin/walk-ins").get_data(as_text=True))
    assert "removed from the queue" in flash_text(post(a, f"/admin/walk-ins/{ids[2]}/end", dict(status="removed", reason="Added twice"), page="/admin/walk-ins").get_data(as_text=True))
    assert "no longer waiting" in flash_text(post(a, f"/admin/walk-ins/{ids[1]}/end", dict(status="left"), page="/admin/walk-ins").get_data(as_text=True))
    con = sqlite3.connect(app.config["DATABASE"])
    stale = con.execute("INSERT INTO walk_ins (user_id, specialty, visit_date, checked_in_at) VALUES (?, 'Walk-in Clinic', ?, ?)",
                        (jo_id, (today - timedelta(days=1)).isoformat(), "2000-01-01 09:00:00")).lastrowid
    con.commit(); con.close()
    a.get("/admin/walk-ins")
    con = sqlite3.connect(app.config["DATABASE"])
    assert con.execute("SELECT status FROM walk_ins WHERE id = ?", (stale,)).fetchone()[0] == "closed"
    con.close()
    assert a.get("/admin/walk-ins").status_code == 200 and c.get("/admin/walk-ins").status_code == 403
    print("admin queue actions ok")

    # Guests: auto-merge on sign-up only when email matches too; otherwise staff merge
    g3 = app.test_client()
    post(g3, "/register", dict(full_name="Guest Three", email="g3@torontomu.ca", student_id="503333333", password="password123", confirm="password123"))
    post(g3, "/login", dict(email="g3@torontomu.ca", password="password123"))
    assert f1 in g3.get("/appointments").get_data(as_text=True)          # the walk-in visit moved over
    g4 = app.test_client()
    post(g4, "/register", dict(full_name="Guest Four", email="g4.other@torontomu.ca", student_id="504444444", password="password123", confirm="password123"))
    found = a.get("/admin/patients?q=504444444").get_data(as_text=True)
    assert 'tag guest">Guest' in found and "g4.other@torontomu.ca" in found
    guest4 = re.search(r'/admin/patients/(\d+)">Guest 4', found).group(1)
    assert "Merge into account" in a.get(f"/admin/patients/{guest4}").get_data(as_text=True)
    assert "No patient account" in flash_text(post(a, f"/admin/patients/{guest4}/merge", dict(target="nobody@torontomu.ca"), page=f"/admin/patients/{guest4}").get_data(as_text=True))
    r = post(a, f"/admin/patients/{guest4}/merge", dict(target="g4.other@torontomu.ca"), page=f"/admin/patients/{guest4}")
    assert "Merged the guest record" in r.get_data(as_text=True)
    assert a.get(f"/admin/patients/{guest4}").status_code == 404
    assert 'tag guest">Guest' not in a.get("/admin/patients?q=504444444").get_data(as_text=True)
    print("guest merge ok")

    # Stats: walk-ins counted separately, released slots never counted twice
    dash = a.get("/admin/dashboard").get_data(as_text=True)
    assert re.search(r"<dt>Walk-ins seen</dt><dd>3</dd>", dash) and re.search(r"<dt>Waiting now</dt><dd>0", dash)
    assert re.search(r"<dt>Left without being seen</dt><dd>1</dd>", dash), re.findall(r"<dd>.*?</dd>", dash)
    rep = a.get(f"/admin/reports?start={today}&end={today}").get_data(as_text=True)
    row = re.search(r"<td>Walk-in Clinic</td>(.*?)</tr>", rep, re.S).group(1)
    nums = re.findall(r'<td class="num">(\d+)', row)
    # Slots, filled, upcoming, completed, no-shows, cancelled, walk-ins, left unseen
    assert nums == ["12", "5", "4", "1", "2", "0", "3", "1"], nums
    print("walk-in stats ok")


print("ALL TESTS PASSED")
