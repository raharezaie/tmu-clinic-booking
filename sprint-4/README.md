# TMU Health Booking: Sprint 4 (final version)

The finished TMU clinic booking system: a Flask + SQLite web app for students (patients), clinic doctors and front-desk staff. Sprint 4 covers testing, bug fixing and final improvements on top of Sprint 3 (see `../sprint-3`).

## Quick start

You need Python 3.10 or newer.

```bash
cd sprint-4
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
flask --app app seed-demo         # optional: load demo data for a presentation
flask --app app run --debug
```

Open http://127.0.0.1:5000.

`seed-demo` rebuilds the database with ready-made accounts, all using the password `password123`:

| Role | Log in as | What you'll see |
|---|---|---|
| Clinic admin | `frontdesk@torontomu.ca` | Today's dashboard with every appointment status, a 7-day trend, and a walk-in queue |
| Doctor | `priya.raman@torontomu.ca` | A full day of visits, a patient with her right now, walk-ins waiting |
| Patient | `sam.lee@torontomu.ca` | An upcoming visit he got from the wait list, a new message about it in Messages (plus an older reminder), and a wait list he's on |

Loading the demo also prints the morning's emails in the terminal: tomorrow's reminders, and a "your turn is coming" email for Dan Wu, a walk-in who stepped out. They're listed on the admin's Emails page.

Without `seed-demo`, the app starts with an empty database containing five sample doctors. Use `flask --app app init-db` to wipe everything and start again.

## Features by sprint

| Sprint | Cards | Main files |
|---|---|---|
| 1 | Authentication, patient and admin registration and login, simple booking, simple admin dashboard | `auth.py`, `booking.py`, `admin.py`, `scheduling.py` |
| 2 | Doctor availability page, full appointment booking (review, reschedule, rules) | `doctors.py`, `appointments.py` |
| 3 | Wait list and appointment logic, doctor registration and login, full admin dashboard, doctor dashboard, walk-in queue | `appointments.py`, `doctor_portal.py`, `walkins.py`, `admin.py` |
| 4 | Testing, bug fixing, final improvements | `tests/`, `demo.py`, and the fixes listed below |

How the files map to the DFD:

| DFD | Code |
|---|---|
| 1.0 Authenticate User | `auth.py` |
| 2.0 Search Availability | `scheduling.py`, `doctors.py`, `booking.py` |
| 3.0 Book Appointment | `appointments.py` (rules, wait list, statuses), `booking.py` (patient pages) |
| 4.0 Admin Dashboard | `admin.py`, plus `walkins.py` (front desk) and `doctor_portal.py` (doctors) |
| D1 User DB | `users` table |
| D2 Doctor Sched DB | `doctors`, `doctor_schedules` tables |
| D3 Appointments DB | `appointments`, `waitlist`, `walk_ins`, `notifications`, `emails` tables |

## Sprint 4: testing

`tests/` holds 94 automated tests written with pytest. Each test gets its own throwaway database, so tests never change your `clinic.db`.

```bash
pytest            # run everything (about 30 seconds)
pytest -v         # list each test by name
pytest tests/test_waitlist.py   # one area only
```

| File | Covers |
|---|---|
| `test_auth.py` | Registration rules, login, account lockout, role access, CSRF, safe redirects, doctor sign-up |
| `test_booking.py` | Availability pages, booking rules, double-booking, reschedule, cancel, the 2-hour cutoff, privacy between patients |
| `test_waitlist.py` | Joining, queue order, automatic booking, skipping patients who can't take a slot, notifications, expiry |
| `test_clinic.py` | Check in, complete, no-show, dashboards, weekly hours, CSV export, the database commands |
| `test_walkins.py` | Front-desk form, urgent-first ordering, doctors calling patients, who can finish whom |
| `test_notifications.py` | Day-before reminders (once only, only tomorrow, reset on reschedule), the patient message center, walk-in "stepped out" emails, email log, mail server failures |

## Sprint 4: bugs fixed

Each bug was reproduced in the Sprint 3 code before it was fixed, and each fix has a test so it can't come back.

| # | Bug | Fix | Test |
|---|---|---|---|
| 1 | Two accounts could register with the same student number. | Clear error at sign-up, plus a unique index in the database. | `test_duplicate_student_number_is_refused` |
| 2 | "Booked on" dates were saved in UTC, so evening bookings in Toronto showed tomorrow's date. | Timestamps are saved in local time. | `test_booked_on_date_uses_local_time` |
| 3 | When a doctor added hours to a fully booked day, patients on that day's wait list weren't booked into them. | New hours go to the wait list first. | `test_new_hours_go_to_the_wait_list_first` |
| 4 | Patients could join the wait list for a day whose hours were already over, so it could never be filled. | The wait list is only offered when there's still time left to fill. Otherwise the page says "No times left". | `test_no_wait_list_for_a_day_that_is_already_over` |
| 5 | Status tags like "Checked-in" wrapped onto two lines in the admin table. | Tags no longer wrap. | Checked visually |
| 6 | The `init-db` command didn't work when run by the test runner (it worked from the terminal). | Commands now set up the app themselves. | `test_init_db_command_rebuilds_an_empty_database` |

## Sprint 4: email notifications

| Who | When they're emailed | Where staff and patients see it was sent |
|---|---|---|
| **Walk-ins who stepped out** | When there are 2 people ahead of them, and again when a doctor calls them in | The walk-in queue shows "Stepped out", then a green "✓ Emailed ... at 14:05" |
| **Patients with a booking** | A reminder the day before the appointment | In the patient's **Messages** page, and "✓ Reminder emailed" on My appointments, the admin dashboard and the doctor's day. The admin dashboard also shows "4 of 6 of tomorrow's patients emailed". |
| **Patients booked from the wait list** | As soon as they're booked | In the patient's **Messages** page, plus the email |
| **Patients whose appointment the clinic cancels** | Right away | In the patient's **Messages** page, plus the email |

### Patient message center

Patients have a **Messages** page (in the menu, with a gold badge counting new messages). It lists every reminder and update they've received, newest first. Each message shows when it was emailed and links to its appointment. New messages are highlighted the first time they're opened and then kept as history. If an email doesn't go through, the message is still there, and only the email is tried again later.

**Walk-ins:** the front desk adds an email on the walk-in form (or it's taken from their account if they give a student number) and ticks "Stepping out". A walk-in already in the queue can be marked "Stepped out", and "Back in room" again when they return. Each email is sent only once.

**Reminders** go out automatically while the app is running (it checks every 10 minutes), from the dashboard's **Send now** button, or from a terminal or scheduled job:

```bash
flask --app app send-reminders
```

Rescheduling clears the reminder, so the patient gets one for the new date.

**Every email is listed on the admin's Emails page**, with its full text and whether it was sent, printed or failed.

### Sending real emails

Without a mail server, which is the default, emails are **printed in the terminal** where `flask run` is running and logged on the Emails page. That works well for demos. To send real emails, for example from a Gmail account:

1. Turn on 2-Step Verification for the Gmail account, then create an **app password** at https://myaccount.google.com/apppasswords.
2. Start the app with:

```bash
export MAIL_SERVER=smtp.gmail.com
export MAIL_USERNAME=yourclinicaccount@gmail.com
export MAIL_PASSWORD="the 16-letter app password"
flask --app app run --debug
```

On Windows, use `set` instead of `export`. If sending fails, the page still works, and the email shows as "Failed" on the Emails page and is retried later.

## Sprint 4: final improvements

- **Account lockout:** after 5 wrong passwords in a row, the account is locked for 15 minutes, which stops password guessing.
- **Demo data:** `flask --app app seed-demo` loads a realistic clinic day for presentations.
- **CSV export:** "Download CSV" on the admin dashboard saves the day's appointments as a spreadsheet. Text that could run as a spreadsheet formula is made safe.
- **Default code warning:** if the app runs outside debug mode with the default secret key or invite codes, it prints a warning, since those values are public on GitHub.
- **Old database message:** a `clinic.db` from an earlier sprint shows a page explaining how to rebuild it, instead of crashing.
- **Phone layout:** tidier header spacing on small screens.

## Settings

| Environment variable | Default (development only) |
|---|---|
| `SECRET_KEY` | `dev-only-change-me` |
| `ADMIN_INVITE_CODE` | `TMU-STAFF-2026` |
| `DOCTOR_INVITE_CODE` | `TMU-DOCTOR-2026` |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM` | Not set (emails are printed). Port defaults to 587 with TLS. |
| `APP_URL` | `http://127.0.0.1:5000` (used for links inside emails) |

Change the first three before real people use the app.

## Project structure

```
app.py            Creates the app, settings, error pages
auth.py           Registration (patient, admin, doctor), login, lockout, role checks, CSRF
appointments.py   Booking rules, wait list, appointment statuses (one place for all rules)
scheduling.py     Turns weekly shifts into 30-minute slots; editing shifts
booking.py        Patient pages: search, review, book, my appointments, reschedule, wait list, messages
doctors.py        Doctor availability pages
doctor_portal.py  Doctor dashboard and weekly hours
admin.py          Admin dashboard, CSV export, doctor management
walkins.py        Walk-in queue (front desk), queue logic, stepped-out emails
mailer.py         Sends emails (or prints them) and logs every one
reminders.py      Day-before reminders: automatic check, send-reminders command
db.py             Database connection, init-db, schema version check
demo.py           seed-demo command
schema.sql        All tables
templates/        HTML pages
static/style.css  Styling
tests/            pytest test suite
```
