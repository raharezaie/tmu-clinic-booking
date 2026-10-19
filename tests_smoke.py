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


print("ALL TESTS PASSED")
