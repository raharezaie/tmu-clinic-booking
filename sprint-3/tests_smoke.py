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
assert "Choose another slot" in r.get_data(as_text=True); print("bad slot ok")
# no csrf
assert c.post("/book", data=dict(doctor_id=1, date=d.isoformat(), time="09:30")).status_code == 400; print("csrf ok")

c2 = app.test_client()
post(c2, "/register", dict(full_name="Jo Park", email="jo@torontomu.ca", student_id="501111111", password="password123", confirm="password123"))
post(c2, "/login", dict(email="jo@torontomu.ca", password="password123"))
r = post(c2, "/book", dict(doctor_id=1, date=d.isoformat(), time="09:00"), page="/book")
assert "just booked" in r.get_data(as_text=True)
r = post(c2, "/book", dict(doctor_id=3, date=d.isoformat(), time="13:30"), page="/book")
assert "Booked" in r.get_data(as_text=True); print("double-book blocked ok")
# cancel
appts = c2.get("/appointments").get_data(as_text=True)
aid = re.search(r'/appointments/(\d+)"', appts).group(1)
assert c.post(f"/appointments/{aid}/cancel", data={"csrf": tok(c, "/appointments")}).status_code == 404
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


print("SPRINT 1 CHECKS PASSED")



# ---------- Sprint 2 checks: doctor availability, review step, full booking rules ----------
app = create_app({"DATABASE": os.path.join(tempfile.mkdtemp(), "s2.db"), "TESTING": True})

def nextwd(wd, offset=1):
    d = date.today() + timedelta(days=offset)
    while d.weekday() != wd: d += timedelta(days=1)
    return d

c = app.test_client()
post(c, "/register", dict(full_name="Sam Lee", email="sam@torontomu.ca", student_id="501234567", password="password123", confirm="password123"))
post(c, "/login", dict(email="sam@torontomu.ca", password="password123"))
p = c.get("/doctors/").get_data(as_text=True)
assert "Dr. Priya Raman" in p and "Next open" in p and "Mon" in p, p[:500]
p = c.get("/doctors/?specialty=Mental+Health").get_data(as_text=True); assert "Bello" in p and "Raman" not in p
mon = nextwd(0, 3)
p = c.get(f"/doctors/1?start={mon}").get_data(as_text=True)
assert "/book/review?" in p and "Not working" in p, "detail"
p = c.get(f"/book/review?doctor_id=1&date={mon}&time=09:00").get_data(as_text=True)
assert "Confirm your booking" in p
p = c.get(f"/book/review?doctor_id=1&date={mon}&time=09:10", follow_redirects=True).get_data(as_text=True)
assert "isn&#39;t in the doctor" in p
r = post(c, "/book", dict(doctor_id=1, date=mon.isoformat(), time="09:00", reason="Checkup"), page="/book")
t = r.get_data(as_text=True); assert "Booked with" in t and "Reschedule" in t, t[:300]
aid = int(re.search(r"/appointments/(\d+)/reschedule", t).group(1))
# same doctor same day blocked
t = post(c, "/book", dict(doctor_id=1, date=mon.isoformat(), time="10:00"), page="/book").get_data(as_text=True)
assert "with this doctor that day" in t
# limit of 3
wed = nextwd(2, 3); fri = nextwd(4, 3)
for d, doc, tm in [(mon, 3, "13:00"), (wed, 1, "09:00")]:
    assert "Booked with" in post(c, "/book", dict(doctor_id=doc, date=d.isoformat(), time=tm), page="/book").get_data(as_text=True)
t = post(c, "/book", dict(doctor_id=4, date=fri.isoformat(), time="09:00"), page="/book").get_data(as_text=True)
assert "up to 3 upcoming" in t
# reschedule
p = c.get(f"/appointments/{aid}/reschedule?start={mon}").get_data(as_text=True)
assert 'name="time" value="09:30"' in p and 'value="09:00"' not in p
t = post(c, f"/appointments/{aid}/reschedule", dict(date=mon.isoformat(), time="10:30")).get_data(as_text=True)
assert "Moved to" in t and "10:30" in t
t = post(c, f"/appointments/{aid}/reschedule", dict(date=mon.isoformat(), time="10:31")).get_data(as_text=True)
assert "isn&#39;t in the doctor" in t
# cancel, then can book 4th
assert "Appointment cancelled" in post(c, f"/appointments/{aid}/cancel", {}, page=f"/appointments/{aid}").get_data(as_text=True)
assert "Booked with" in post(c, "/book", dict(doctor_id=4, date=fri.isoformat(), time="09:00"), page="/book").get_data(as_text=True)
# other patient can't see / cancel
c2 = app.test_client()
post(c2, "/register", dict(full_name="Jo", email="jo@torontomu.ca", student_id="501111111", password="password123", confirm="password123"))
post(c2, "/login", dict(email="jo@torontomu.ca", password="password123"))
assert c2.get(f"/appointments/{aid}").status_code == 404
# cutoff: appointment starting within 2 hours can't be cancelled
from datetime import datetime
with app.app_context():
    from db import get_db
    soon = datetime.now() + timedelta(minutes=60)
    get_db().execute("INSERT INTO appointments (patient_id, doctor_id, appt_date, start_time) VALUES (2, 2, ?, ?)",
                     (soon.date().isoformat(), soon.strftime("%H:%M"))); get_db().commit()
    sid = get_db().execute("select max(id) from appointments").fetchone()[0]
t = c2.get(f"/appointments/{sid}").get_data(as_text=True); assert "less than 2 hours" in t
t = post(c2, f"/appointments/{sid}/cancel", {}, page="/appointments").get_data(as_text=True); assert "less than 2 hours" in t
assert c.get("/appointments").status_code == 200
# admin can view doctors page
a = app.test_client()
post(a, "/admin/register", dict(full_name="Admin", email="adm@torontomu.ca", invite_code="TMU-STAFF-2026", password="adminpass1", confirm="adminpass1"))
post(a, "/login", dict(email="adm@torontomu.ca", password="adminpass1"))
p = a.get(f"/doctors/1?start={mon}").get_data(as_text=True); assert "chip static" in p and "/book/review" not in p
assert a.get("/admin/dashboard").status_code == 200
print("SPRINT 2 CHECKS PASSED")


# ---------- Sprint 3 checks: doctors, wait list, status logic, walk-ins, full dashboards ----------
import sqlite3
from datetime import datetime
app = create_app({"DATABASE": os.path.join(tempfile.mkdtemp(), "s3.db"), "TESTING": True})

def client_for(email, password, register=None, kind="patient"):
    c = app.test_client()
    if register:
        page = {"patient": "/register", "admin": "/admin/register", "doctor": "/doctor/register"}[kind]
        post(c, page, register)
    t = post(c, "/login", dict(email=email, password=password)).get_data(as_text=True)
    return c, t

def patient(n):
    email = f"p{n}@torontomu.ca"
    c, _ = client_for(email, "password123", dict(full_name=f"Patient {n}", email=email, student_id=f"50000000{n}",
                                                 password="password123", confirm="password123"))
    return c

def db_query(sql, args=()):
    with app.app_context():
        from db import get_db
        cur = get_db().execute(sql, args); rows = cur.fetchall(); get_db().commit(); return rows

# Doctor registration
d = dict(full_name="Dr. Priya Raman", email="priya.raman@torontomu.ca", password="doctorpass1", confirm="doctorpass1")
c = app.test_client()
assert "Doctor invite code is incorrect" in post(c, "/doctor/register", dict(d, invite_code="nope")).get_data(as_text=True)
t = post(c, "/doctor/register", dict(d, invite_code="TMU-DOCTOR-2026")).get_data(as_text=True)
assert "linked to your existing profile" in t, t[:400]
t = post(c, "/doctor/register", dict(d, email="priya.raman@torontomu.ca", invite_code="TMU-DOCTOR-2026")).get_data(as_text=True)
assert "already has an account" in t
t = post(c, "/doctor/register", dict(d, full_name="Dr. New", email="new.doc@torontomu.ca", invite_code="TMU-DOCTOR-2026")).get_data(as_text=True)
assert "Enter your specialty" in t
t = post(c, "/doctor/register", dict(d, full_name="Dr. Nina Park", email="nina.park@torontomu.ca", specialty="Dermatology",
                                     department="Skin Clinic", invite_code="TMU-DOCTOR-2026")).get_data(as_text=True)
assert "add your weekly hours" in t
doc, t = client_for("nina.park@torontomu.ca", "doctorpass1")
assert "Dr. Nina Park" in t and "not scheduled to work" in t, t[:300]
assert doc.get("/book").status_code == 403 and doc.get("/admin/dashboard").status_code == 403
priya, t = client_for("priya.raman@torontomu.ca", "doctorpass1")
assert "Dr. Priya Raman" in t and "General Practice" in t
print("doctor registration ok")

# Doctor hours: Nina works one hour on a day >= 3 days away (2 slots) and all of today
future = date.today() + timedelta(days=3)
t = post(doc, "/doctor/hours", dict(action="add", weekday=future.weekday(), start_time="09:00", end_time="10:00")).get_data(as_text=True)
assert "Shift added" in t
t = post(doc, "/doctor/hours", dict(action="add", weekday=future.weekday(), start_time="09:30", end_time="11:00")).get_data(as_text=True)
assert "overlaps" in t
t = post(doc, "/doctor/hours", dict(action="add", weekday=future.weekday(), start_time="12:15", end_time="13:00")).get_data(as_text=True)
assert "half hour" in t
t = post(doc, "/doctor/hours", dict(action="add", weekday=future.weekday(), start_time="14:00", end_time="13:00")).get_data(as_text=True)
assert "end after" in t
if date.today().weekday() != future.weekday():
    assert "Shift added" in post(doc, "/doctor/hours", dict(action="add", weekday=date.today().weekday(),
                                                              start_time="07:00", end_time="20:30")).get_data(as_text=True)
nina = db_query("SELECT id FROM doctors WHERE email = 'nina.park@torontomu.ca'")[0]["id"]
print("doctor hours ok")

# Wait list: fill both slots, two patients wait, cancellations hand slots over in order
pa, pb, pc, pd = patient(1), patient(2), patient(3), patient(4)
F = future.isoformat()
for p, tm in [(pa, "09:00"), (pb, "09:30")]:
    assert "Booked with" in post(p, "/book", dict(doctor_id=nina, date=F, time=tm), page="/book").get_data(as_text=True)
t = pc.get(f"/book?date={F}&specialty=Dermatology").get_data(as_text=True)
assert "Join wait list" in t
t = pc.get(f"/doctors/{nina}?start={F}").get_data(as_text=True)
assert "Join wait list" in t
t = post(pc, "/waitlist", dict(doctor_id=nina, date=F), page="/appointments").get_data(as_text=True)
assert "on the wait list" in t and "#1" in t, t[:600]
assert "already on the wait list" in post(pc, "/waitlist", dict(doctor_id=nina, date=F), page="/appointments").get_data(as_text=True)
assert "#2" in post(pd, "/waitlist", dict(doctor_id=nina, date=F), page="/appointments").get_data(as_text=True)
assert "open times that day" in post(pd, "/waitlist", dict(doctor_id=1, date=(date.today() + timedelta(days=7 - date.today().weekday())).isoformat()), page="/appointments").get_data(as_text=True)
# A cancels -> C gets 09:00 automatically
aid = db_query("SELECT id FROM appointments WHERE start_time = '09:00' AND doctor_id = ?", (nina,))[0]["id"]
post(pa, f"/appointments/{aid}/cancel", {}, page=f"/appointments/{aid}")
row = db_query("SELECT * FROM appointments WHERE doctor_id = ? AND start_time = '09:00' AND status = 'booked'", (nina,))[0]
assert row["patient_id"] == db_query("SELECT id FROM users WHERE email='p3@torontomu.ca'")[0]["id"] and row["source"] == "waitlist"
t = pc.get("/appointments").get_data(as_text=True)
assert "spot opened up" in t and 'class="badge"' in t and "Wait lists you" not in t
post(pc, "/notifications/read", {}, page="/appointments")
assert 'class="badge"' not in pc.get("/appointments").get_data(as_text=True)
assert "#1" in pd.get("/appointments").get_data(as_text=True)
print("wait list auto-booking ok")
# Clinic (admin) cancels C's booking -> D gets it, C is told
adm, t = client_for("adm@torontomu.ca", "adminpass1", dict(full_name="Front Desk", email="adm@torontomu.ca",
                    invite_code="TMU-STAFF-2026", password="adminpass1", confirm="adminpass1"), kind="admin")
t = adm.get(f"/admin/dashboard?date={F}").get_data(as_text=True)
assert "Patient 4" in t and "From wait list" in t
t = post(adm, f"/admin/appointments/{row['id']}/cancel", {}, page=f"/admin/dashboard?date={F}").get_data(as_text=True)
assert "went to Patient 4 from the wait list" in t, t[:600]
assert "The clinic cancelled" in pc.get("/appointments").get_data(as_text=True)
print("clinic cancel + notify ok")

# Removing a shift with bookings is refused
shift = db_query("SELECT id FROM doctor_schedules WHERE doctor_id = ? AND weekday = ? AND start_time = '09:00'", (nina, future.weekday()))[0]["id"]
assert "fall in this shift" in post(doc, "/doctor/hours", dict(action="remove", shift_id=shift)).get_data(as_text=True)
# Admin can manage hours too
assert "Weekly hours: Dr. Nina Park" in adm.get(f"/admin/doctors/{nina}/hours").get_data(as_text=True)
t = adm.get("/admin/doctors").get_data(as_text=True)
assert "Linked" in t and "No login yet" in t

# Status logic on today's appointments (inserted directly so the test works at any time of day)
T = date.today().isoformat()
pid = db_query("SELECT id FROM users WHERE email='p2@torontomu.ca'")[0]["id"]
db_query("INSERT INTO appointments (patient_id, doctor_id, appt_date, start_time) VALUES (?, ?, ?, '00:00')", (pid, nina, T))
db_query("INSERT INTO appointments (patient_id, doctor_id, appt_date, start_time) VALUES (?, ?, ?, '23:30')", (pid + 1, nina, T))
db_query("INSERT INTO appointments (patient_id, doctor_id, appt_date, start_time) VALUES (?, ?, ?, '00:30')", (pid + 2, nina, T))
early, late, other = [r["id"] for r in db_query("SELECT id FROM appointments WHERE appt_date = ? AND doctor_id = ? ORDER BY start_time", (T, nina))][:1] + \
    [db_query("SELECT id FROM appointments WHERE appt_date = ? AND start_time = '23:30'", (T,))[0]["id"],
     db_query("SELECT id FROM appointments WHERE appt_date = ? AND start_time = '00:30'", (T,))[0]["id"]]
t = adm.get("/admin/dashboard").get_data(as_text=True)
assert "Check in" in t and "Last 7 days" in t
assert "checked in" in post(adm, f"/admin/appointments/{early}/check-in", {}, page="/admin/dashboard").get_data(as_text=True)
assert "Only booked appointments can be checked in" in post(adm, f"/admin/appointments/{early}/check-in", {}, page="/admin/dashboard").get_data(as_text=True)
t = post(doc, f"/doctor/appointments/{early}/complete", dict(notes="Advised rest."), page="/doctor/dashboard").get_data(as_text=True)
assert "marked complete" in t and "Advised rest." in t
assert "after the appointment" in post(adm, f"/admin/appointments/{late}/no-show", {}, page="/admin/dashboard").get_data(as_text=True)
assert "no-show" in post(doc, f"/doctor/appointments/{other}/no-show", {}, page="/doctor/dashboard").get_data(as_text=True)
assert "cancelled" in post(doc, f"/doctor/appointments/{late}/cancel", {}, page="/doctor/dashboard").get_data(as_text=True)
st = {r["id"]: (r["status"], r["visit_notes"], r["cancelled_by"]) for r in db_query("SELECT * FROM appointments WHERE appt_date = ?", (T,))}
assert st[early] == ("completed", "Advised rest.", None) and st[other][0] == "no_show" and st[late] == ("cancelled", None, "clinic")
assert post(priya, f"/doctor/appointments/{early}/complete", {}, page="/doctor/dashboard").status_code == 404
print("appointment status logic ok")

# Walk-in queue
assert pa.get("/walk-ins/").status_code == 403 and doc.get("/walk-ins/").status_code == 403
t = post(adm, "/walk-ins/", dict(patient_name="", reason="")).get_data(as_text=True)
assert "Enter the patient" in t and "Enter the reason" in t
off_doc = [r["id"] for r in db_query("SELECT d.id FROM doctors d WHERE NOT EXISTS (SELECT 1 FROM doctor_schedules s WHERE s.doctor_id = d.id AND s.weekday = ?)", (date.today().weekday(),))]
if off_doc:
    assert "isn&#39;t working today" in post(adm, "/walk-ins/", dict(patient_name="X", reason="Y", preferred_doctor_id=off_doc[0])).get_data(as_text=True)
assert "added to the walk-in queue" in post(adm, "/walk-ins/", dict(patient_name="Alex Kim", reason="Sore throat", urgency="normal", student_id="500000001")).get_data(as_text=True)
assert "added to the walk-in queue" in post(adm, "/walk-ins/", dict(patient_name="Bea Lin", reason="Allergic reaction", urgency="urgent")).get_data(as_text=True)
assert "added to the walk-in queue" in post(adm, "/walk-ins/", dict(patient_name="Cy Roy", reason="Rash", urgency="normal", preferred_doctor_id=nina)).get_data(as_text=True)
t = adm.get("/walk-ins/").get_data(as_text=True)
assert t.index("Bea Lin") < t.index("Alex Kim") < t.index("Cy Roy") and "(has an account)" in t
assert "3 waiting" in doc.get("/doctor/dashboard").get_data(as_text=True)
t = post(doc, "/doctor/walk-ins/call-next", {}, page="/doctor/dashboard").get_data(as_text=True)
assert "Called in Bea Lin (urgent)" in t and "With you: Bea Lin" in t
bea = db_query("SELECT id FROM walk_ins WHERE patient_name='Bea Lin'")[0]["id"]
assert "Finished with Bea Lin" in post(doc, f"/doctor/walk-ins/{bea}/done", {}, page="/doctor/dashboard").get_data(as_text=True)
cy = db_query("SELECT id FROM walk_ins WHERE patient_name='Cy Roy'")[0]["id"]
alex = db_query("SELECT id FROM walk_ins WHERE patient_name='Alex Kim'")[0]["id"]
t = post(adm, f"/walk-ins/{cy}/assign", dict(doctor_id=1), page="/walk-ins/").get_data(as_text=True)
assert "asked for a different doctor" in t or "working today" in t
assert "sent in" in post(adm, f"/walk-ins/{cy}/assign", dict(doctor_id=nina), page="/walk-ins/").get_data(as_text=True)
assert "marked as left" in post(adm, f"/walk-ins/{alex}/status", dict(status="left"), page="/walk-ins/").get_data(as_text=True)
assert "marked as done" in post(adm, f"/walk-ins/{cy}/status", dict(status="done"), page="/walk-ins/").get_data(as_text=True)
assert "No walk-ins are waiting" in post(doc, "/doctor/walk-ins/call-next", {}, page="/doctor/dashboard").get_data(as_text=True)
t = adm.get("/walk-ins/").get_data(as_text=True); assert "Finished today (3)" in t
print("walk-in queue ok")

# Old database from Sprint 1/2 gives a clear message
old = os.path.join(tempfile.mkdtemp(), "old.db"); sqlite3.connect(old).execute("CREATE TABLE x (y)").connection.commit()
old_app = create_app({"DATABASE": old, "TESTING": True})
r = old_app.test_client().get("/login"); assert r.status_code == 500 and b"init-db" in r.data
print("old database message ok")
print("SPRINT 3 CHECKS PASSED")
