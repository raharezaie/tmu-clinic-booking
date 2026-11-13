"""2.0 Search Availability and 3.0 Book Appointment: availability pages and booking rules."""
from datetime import date, timedelta

from conftest import in_minutes, weekday_ahead


def book(b, doctor_id, day, time, reason=""):
    return b.text("/book", dict(doctor_id=doctor_id, date=day.isoformat(), time=time, reason=reason), from_page="/book")


# ---------- Finding a time ----------
def test_search_shows_doctors_working_that_day_with_open_times(site, monday):
    page = site.patient().page(f"/book?date={monday}")
    assert "Dr. Priya Raman" in page and 'value="09:00"' in page
    assert "Dr. Marcus Chen" not in page  # doesn't work Mondays


def test_search_can_filter_by_specialty(site, monday):
    page = site.patient().page(f"/book?date={monday}&specialty=Mental+Health")
    assert "Dr. Aisha Bello" in page and "Dr. Priya Raman" not in page


def test_doctor_list_shows_hours_and_next_open_time(site):
    page = site.patient().page("/doctors/")
    assert "Dr. Priya Raman" in page and "Next open" in page and "09:00–12:00" in page


def test_doctor_week_links_each_open_time_to_the_review_step(site, monday):
    page = site.patient().page(f"/doctors/1?start={monday}")
    assert f"/book/review?doctor_id=1&amp;date={monday}&amp;time=09:00" in page
    assert "Not working" in page


def test_staff_see_availability_but_cannot_book_from_it(site, monday):
    page = site.admin().page(f"/doctors/1?start={monday}")
    assert "chip static" in page and "/book/review" not in page


def test_review_step_confirms_details_before_booking(site, monday):
    b = site.patient()
    assert "Confirm your booking" in b.page(f"/book/review?doctor_id=1&date={monday}&time=09:00")
    assert "isn&#39;t in the doctor" in b.page(f"/book/review?doctor_id=1&date={monday}&time=09:10")


# ---------- Booking ----------
def test_booking_appears_in_my_appointments_with_details(site, monday):
    b = site.patient()
    page = book(b, 1, monday, "09:00", "Checkup")
    assert "Booked with Dr. Priya Raman" in page and "Checkup" in page and "Reschedule" in page
    assert "09:00" in b.page("/appointments")
    assert 'value="09:00"' not in b.page(f"/book?date={monday}")  # slot no longer offered


def test_booked_on_date_uses_local_time(site, monday):
    """Sprint 4 bug fix: dates were stored in UTC, so evening bookings showed tomorrow's date."""
    book(site.patient(), 1, monday, "09:00")
    assert site.one("SELECT created_at FROM appointments")["created_at"][:10] == date.today().isoformat()


def test_times_outside_the_schedule_or_window_are_refused(site, monday):
    b = site.patient()
    assert "isn&#39;t in the doctor" in book(b, 1, monday, "09:10")
    assert "isn&#39;t in the doctor" in book(b, 1, monday, "13:00")
    far = date.today() + timedelta(days=45)
    assert "Choose a date between" in book(b, 1, far, "09:00")


def test_two_patients_cannot_book_the_same_slot(site, monday):
    book(site.patient(1), 1, monday, "09:00")
    assert "Someone just booked that slot" in book(site.patient(2), 1, monday, "09:00")


def test_patient_cannot_be_in_two_places_at_once(site, monday):
    b = site.patient()
    book(b, 3, monday, "13:00")
    b2 = weekday_ahead(4)  # Friday: Dr. Raman 13:00-16:00, Dr. Okafor 09:00-12:00, Dr. Marino 09:00-13:00
    book(b, 4, b2, "09:00")
    assert "already have an appointment at that time" in book(b, 5, b2, "09:00")


def test_one_appointment_per_doctor_per_day(site, monday):
    b = site.patient()
    book(b, 1, monday, "09:00")
    assert "with this doctor that day" in book(b, 1, monday, "10:00")


def test_at_most_three_upcoming_appointments(site, monday):
    b = site.patient()
    wednesday, friday = weekday_ahead(2), weekday_ahead(4)
    for doctor, day, time in [(1, monday, "09:00"), (3, monday, "13:00"), (1, wednesday, "09:00")]:
        assert "Booked with" in book(b, doctor, day, time)
    assert "up to 3 upcoming" in book(b, 4, friday, "09:00")


# ---------- Changing a booking ----------
def test_reschedule_moves_the_booking_and_frees_the_old_slot(site, monday):
    b = site.patient()
    book(b, 1, monday, "09:00")
    appt = site.one("SELECT id FROM appointments")["id"]
    page = b.page(f"/appointments/{appt}/reschedule?start={monday}")
    assert 'value="09:30"' in page
    assert "Moved to" in b.text(f"/appointments/{appt}/reschedule", dict(date=monday.isoformat(), time="10:30"))
    assert site.one("SELECT start_time FROM appointments")["start_time"] == "10:30"
    assert 'value="09:00"' in site.patient(2).page(f"/book?date={monday}")


def test_cancel_frees_the_slot_and_allows_a_new_booking(site, monday):
    b = site.patient()
    book(b, 1, monday, "09:00")
    appt = site.one("SELECT id FROM appointments")["id"]
    assert "Appointment cancelled" in b.text(f"/appointments/{appt}/cancel", from_page=f"/appointments/{appt}")
    assert site.one("SELECT status, cancelled_by FROM appointments")[:] == ("cancelled", "patient")
    assert "Booked with" in book(site.patient(2), 1, monday, "09:00")


def test_no_changes_within_two_hours_of_the_start(site):
    b = site.patient()
    day, time = in_minutes(60)
    appt = site.appointment(b.user_id, 1, day, time)
    assert "less than 2 hours" in b.page(f"/appointments/{appt}")
    assert "less than 2 hours" in b.text(f"/appointments/{appt}/cancel", from_page="/appointments")
    assert site.one("SELECT status FROM appointments")["status"] == "booked"


def test_patients_cannot_see_or_change_each_others_appointments(site, monday):
    book(site.patient(1), 1, monday, "09:00")
    appt = site.one("SELECT id FROM appointments")["id"]
    other = site.patient(2)
    assert other.get(f"/appointments/{appt}").status_code == 404
    assert other.post(f"/appointments/{appt}/cancel", from_page="/appointments", follow=False).status_code == 404
