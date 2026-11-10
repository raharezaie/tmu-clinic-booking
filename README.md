# TMU Health Booking

A Flask + SQLite web app for the TMU clinic. Sprint 1 covered the five cards on the board:

| Sprint 1 card | Where it lives | DFD link |
|---|---|---|
| Authentication (backend) | `auth.py`: password hashing, sessions, role checks, CSRF protection | 1.0 Authenticate User, D1 User DB |
| Patient registration and login | `/register`, `/login` (requires an @torontomu.ca email and a 9-digit student number) | E1, 1.0, D1 |
| Clinic admin registration and login | `/admin/register` (requires the staff invite code), `/login` | E2, 1.0, D1 |
| Appointment booking (simple version) | `/book`, `/appointments` in `booking.py`, slot logic in `scheduling.py` | 2.0 Search Availability, 3.0 Book Appointment, D2, D3 |
| Clinic admin dashboard (simple version) | `/admin/dashboard` in `admin.py` | 4.0 Admin Dashboard, D3 |

Since then, the **full clinic admin dashboard** has been added:

| Feature | Where it lives |
|---|---|
| Manage appointments: mark completed / no-show, cancel, book for a patient | `/admin/dashboard`, `/admin/book` in `admin.py` |
| Manage doctors: add, edit, deactivate | `/admin/doctors` in `doctors_admin.py` |
| Edit schedules: weekly shifts and days off | `/admin/doctors/<id>` in `doctors_admin.py` |
| Patient lookup and visit history | `/admin/patients` in `reports.py` |
| Reports over a date range, by doctor and specialty | `/admin/reports` in `reports.py` |
| Doctor accounts: staff invite a doctor by email, the doctor sets a password from the link | `/admin/doctors/<id>` (invite), `/doctor/join/<token>` in `doctor_portal.py` |
| Doctor dashboard: own day schedule, mark visits, undo, cancel with a reason, visit notes, own patients and schedule, 30-day stats | `/doctor/home`, `/doctor/appointments/<id>`, `/doctor/patients/<id>`, `/doctor/schedule` in `doctor_dashboard.py` |
| Walk-in queue (backend): tablet check-in, one first-come-first-served queue per specialty, Call next into a free current slot, staff assign / left / remove, wait estimates, guests and guest merge | `/kiosk` in `kiosk.py`, `/admin/walk-ins` and queue rules in `walkins.py`, `/doctor/call-next` |
| Arrival and late release: booked patients check in on the tablet or at the desk; 10 minutes after the start, an un-arrived booking's slot can be released to walk-ins | `/kiosk/arrive`, `/admin/appointments/<id>/arrive`, `.../release`, `/doctor/appointments/<id>/release` |
| Patient visit page: details, the doctor's note for the patient, or why the clinic cancelled | `/appointments/<id>` in `booking.py` |

Status rules live in `appointments.py` and are shared by staff and doctors: visits are marked completed or a no-show only after they start, the clinic must give a reason to cancel (the patient sees it), and only doctors can set a visit back to booked, on the day of the visit. Visit notes have a private part (doctor only) and a part for the patient; they can be written on completed visits and lock 7 days after the visit. Staff see only that a note exists.

Staff can't make a schedule change that would leave a booked patient without a doctor (deactivating, removing a shift, or adding time off). The app lists the affected appointments so staff can cancel or rebook them first.

## Run it

You need Python 3.10 or newer.

```bash
cd tmu_clinic
python -m venv venv
# Windows: venv\Scripts\activate    Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug
```

Open http://127.0.0.1:5000. The database file `clinic.db` is created on first run with five sample doctors and their weekly shifts, plus a demo doctor login for Dr. Priya Raman (`priya.raman@torontomu.ca`, password from `DEMO_DOCTOR_PASSWORD`) and the check-in tablet's login (`kiosk@torontomu.ca`, password from `KIOSK_PASSWORD`). See Settings.

To wipe all accounts and bookings and start fresh (also needed once if your `clinic.db` was created before walk-ins were added, since the tables changed):

```bash
flask --app app init-db
```

## Try it out

1. **Patient:** Go to "Create account", register with any `name@torontomu.ca` email and a 9-digit student number, log in, then book a time on the Book page. Doctors work Monday to Friday only, so pick a weekday.
2. **Clinic admin:** Go to `/admin/register` (also linked from the login page). The staff invite code for development is `TMU-STAFF-2026`. Log in and the dashboard shows the day's bookings, slots filled per doctor, and cancellations. From there:
   - Mark past visits **Completed** or **No-show**, or **Cancel** upcoming ones.
   - **Doctors**: add a doctor, give them weekly shifts, book days off, or deactivate them.
   - **Patients**: search by name, email or student number, see their history, and **Book** on their behalf.
   - **Reports**: pick a date range to see slots filled, completed visits, no-shows and cancellations by doctor and specialty.
3. **Doctor:** As an admin, open a doctor under **Doctors**, enter their `@torontomu.ca` email under **Login**, and copy the invite link (it works once and expires in 7 days). Open the link logged out, choose a password, then log in on the normal login page. Doctors land on their day schedule and can change their password. Deactivating a doctor also blocks their login.
4. **Walk-ins:** Log in as `kiosk@torontomu.ca` (on the clinic tablet). Walk-ins enter their name, student number, TMU email and service; booked patients check in with their student number and email. The tablet's answers never reveal whether an account exists. Someone whose student number *and* email match an account goes on that account; anyone else becomes a guest, who is merged into their account automatically if they later register with the same student number and email (or by staff from their patient page). Doctors use **Call next** on their day view when the slot running now is free; staff see the queue under **Walk-ins**. The tablet page is bare for now; its proper UI is the walk-in form item.

## Project structure

```
app.py          App setup, routes registered, error pages
auth.py         1.0 Authenticate User (register, login, logout, role checks, CSRF)
booking.py      2.0 Search Availability + 3.0 Book Appointment (patient pages)
admin.py        4.0 Admin Dashboard: daily summary, appointment status changes, booking for patients
doctors_admin.py  Staff management of doctors, weekly shifts, time off, and doctor login invites (D2)
doctor_portal.py  Doctor invite links and sign-up from an invite
doctor_dashboard.py  Doctor's day, visit pages with notes, own patients, own schedule
appointments.py Shared rules for status changes (complete, no-show, cancel, undo), arrival, late release, and visit notes
walkins.py      Walk-in queue rules (check-in, estimates, call next, assign, merge guests) and the admin queue page
kiosk.py        Clinic check-in tablet: walk-in check-in and arrival for booked patients
reports.py      Patient lookup and date-range reports
scheduling.py   Turns doctor shifts into 30-minute slots, removes booked/past/time-off ones; shared booking checks
db.py           Database connection, init-db command, sample doctors
schema.sql      Tables: users (D1), doctors + doctor_schedules + doctor_time_off + doctor_invites (D2), appointments + visit_notes + walk_ins (D3)
templates/      HTML pages (Jinja)
static/         style.css
```

## What Sprint 1 already handles

- Passwords are stored hashed, never in plain text.
- Patients can't open the admin dashboard and admins can't book (returns "No access").
- A slot can only be booked once, enforced by a unique index in the database, so two students clicking the same time at once can't both get it.
- The server re-checks every booking: the slot must exist in the doctor's schedule, be in the future, and be within the next 30 days.
- Patients can cancel their own upcoming appointments, and the slot reopens.
- Every form has a CSRF token.

## Settings

| Variable | Default | Change before deploying |
|---|---|---|
| `SECRET_KEY` | `dev-only-change-me` | Yes, set a long random value |
| `ADMIN_INVITE_CODE` | `TMU-STAFF-2026` | Yes |
| `DEMO_DOCTOR_PASSWORD` | `doctorpass1` | Yes, or remove the demo doctor from `db.py` |
| `KIOSK_PASSWORD` | `kioskpass1` | Yes |
| `LATE_GRACE_MINUTES` | `10` | Optional: minutes after the start before a late booking's slot can be released |

## Left for later sprints

- Email verification of @torontomu.ca addresses (Sprint 1 checks the format only)
- Walk-in check-in tablet UI (touch layout, confirmation screen, idle reset) and a styled live queue page
- Rescheduling in one step (today: cancel and rebook) and reminders
- Automated test suite (Sprint 4: Testing)
