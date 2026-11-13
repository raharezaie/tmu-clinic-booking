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
