# TMU Health Booking: Sprint 3

Builds on Sprint 2 (see `../sprint-2`). Sprint 3 covers five cards:

| Sprint 3 card | What it adds | Where it lives |
|---|---|---|
| Wait list and appointment logic (backend) | Patients join a wait list for a doctor's fully booked day. When a booking is cancelled or moved, the slot goes **automatically to the first eligible patient waiting**, who gets a message. Appointments now move through statuses: booked, checked in, completed, no-show, cancelled. | `appointments.py`, new `waitlist` and `notifications` tables |
| Clinic Doctor Registration and Login | `/doctor/register` with a doctor invite code. A doctor whose email matches an existing clinic profile takes it over, with its hours and bookings. | `auth.py`, `templates/doctor_register.html` |
| Full Clinic Admin Dashboard | Check in patients, cancel for the clinic (patient is notified, wait list is served), mark no-shows, see the day's wait list and walk-in queue, a 7-day trend, and manage every doctor's weekly hours. | `admin.py`, `templates/dashboard.html`, `admin_doctors.html` |
| Clinic Doctor Dashboard | The doctor's day: mark visits complete with private notes, mark no-shows, cancel, call the next walk-in, and edit their own weekly hours. | `doctor_portal.py`, `templates/doctor_dashboard.html`, `hours.html` |
| Walk-in queue form | The front desk adds walk-ins (name, reason, urgency, optional student number and doctor). **Urgent patients go first**, then by arrival time. Doctors press "Call next walk-in". | `walkins.py`, `templates/walkins.html` |

### Wait list rules

- Patients can only join the wait list when a doctor's day is fully booked, and can be on up to 3 wait lists at once.
- When a slot opens, the first patient in line who can take it is booked. Anyone who can't take it (a clash at that time, or already at 3 upcoming appointments) is skipped but keeps their place.
- Slots starting within 2 hours aren't handed out, since the patient might not see the message in time.
- Wait list entries for days that have passed expire automatically.

### Appointment status flow

```
booked ──check in──▶ checked_in ──▶ completed
  │                      │
  ├──────────────────────┴──▶ no_show   (only after the start time)
  └──▶ cancelled  (by the patient up to 2 hours before, or by the clinic any time)
```

## Run it

```bash
cd sprint-3
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
flask --app app run --debug
```

**The database structure changed in this sprint.** If you have a `clinic.db` from Sprint 1 or 2, the app shows a message asking you to rebuild it. Run `flask --app app init-db`, which deletes old test accounts and bookings.

| Code | Value (development) |
|---|---|
| Staff invite code | `TMU-STAFF-2026` |
| Doctor invite code | `TMU-DOCTOR-2026` |

To log in as one of the sample doctors, register at `/doctor/register` with their email, for example `priya.raman@torontomu.ca`. The other sample doctors are `marcus.chen@`, `aisha.bello@`, `daniel.okafor@` and `sofia.marino@`, all `@torontomu.ca`.

## Test it

```bash
python3 tests_smoke.py
```

This runs the checks for Sprints 1, 2 and 3. It should end with `SPRINT 3 CHECKS PASSED`.
