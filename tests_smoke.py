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
assert "cancelled" in r.get_data(as_text=True)
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
assert "Welcome, Dr. Marcus Chen" in t and "coming soon" in t and "Change password" in t
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


print("ALL TESTS PASSED")
