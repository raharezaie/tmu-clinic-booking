# TMU Health Booking: Sprint 2

Builds on Sprint 1 (see `../sprint-1`). Sprint 2 covers two cards:

| Sprint 2 card | What it adds | Where it lives |
|---|---|---|
| Doctor Availability Page | A list of every doctor with their weekly hours and next open time (`/doctors`), and a page per doctor showing a week of open times (`/doctors/<id>`). Patients click a time to book it. | `doctors.py`, `scheduling.py` (`weekly_hours`, `next_open_slot`, `availability_week`), `templates/doctors.html`, `doctor_detail.html` |
| Full Appointment Booking | A review step before confirming, an appointment details page, rescheduling, and booking rules (below). | `appointments.py` (all booking rules in one place), `booking.py`, `templates/review.html`, `appointment_detail.html`, `reschedule.html` |

### Booking rules added in Sprint 2

- A patient can hold at most **3 upcoming appointments**.
- **One appointment per doctor per day**. To change the time, reschedule instead.
- Patients can **cancel or reschedule until 2 hours before** the start. After that, they call the clinic.
- Rescheduling keeps the same doctor and frees the old slot for others.

These rules are in `appointments.py` so every page uses the same checks. The DFD process is 3.0 Book Appointment.

## Run it

You need Python 3.10 or newer.

```bash
cd sprint-2
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
flask --app app run --debug
```

Open http://127.0.0.1:5000. A `clinic.db` from Sprint 1 works here too, since the database structure didn't change.

- Staff invite code (development): `TMU-STAFF-2026`
- Wipe all data and start fresh: `flask --app app init-db`

## Test it

```bash
python3 tests_smoke.py
```

This runs the Sprint 1 checks and the new Sprint 2 checks. It should end with `SPRINT 2 CHECKS PASSED`.
