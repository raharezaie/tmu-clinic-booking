"""Wait list and automatic booking when a slot opens up (Sprint 3 backend logic)."""
from datetime import date, timedelta

from conftest import in_minutes


def full_day(site, day):
    """A doctor with two slots (09:00, 09:30) on `day`, both booked by other patients."""
    doctor = site.new_doctor(slots_on=day)
    a, b = site.patient(11), site.patient(12)
    site.appointment(a.user_id, doctor, day, "09:00")
    site.appointment(b.user_id, doctor, day, "09:30")
    return doctor, a, b


def join(b, doctor, day):
    return b.text("/waitlist", dict(doctor_id=doctor, date=day.isoformat()), from_page="/appointments")


def owner_of(site, doctor, day, time):
    row = site.one("SELECT patient_id, source FROM appointments WHERE doctor_id = ? AND appt_date = ? "
                   "AND start_time = ? AND status = 'booked'", (doctor, day.isoformat(), time))
    return row and (row["patient_id"], row["source"])


def cancel_as_patient(site, b, doctor, day, time):
    appt = site.one("SELECT id FROM appointments WHERE doctor_id = ? AND appt_date = ? AND start_time = ? "
                    "AND status = 'booked'", (doctor, day.isoformat(), time))["id"]
    return b.text(f"/appointments/{appt}/cancel", from_page=f"/appointments/{appt}")


def test_join_button_shown_only_when_the_day_is_full(site, monday):
    doctor, _, _ = full_day(site, monday)
    b = site.patient()
    assert "Join wait list" in b.page(f"/book?date={monday}&specialty=Testing")
    assert "Join wait list" in b.page(f"/doctors/{doctor}?start={monday}")
    assert "open times that day" in join(b, 1, monday)  # Dr. Raman still has times


def test_waiting_patients_get_positions_in_order(site, monday):
    doctor, _, _ = full_day(site, monday)
    first, second = site.patient(1), site.patient(2)
    assert "#1" in join(first, doctor, monday)
    assert "#2" in join(second, doctor, monday)
    assert "already on the wait list" in join(first, doctor, monday)


def test_cancellation_books_the_first_waiting_patient_and_tells_them(site, monday):
    doctor, a, _ = full_day(site, monday)
    first, second = site.patient(1), site.patient(2)
    join(first, doctor, monday)
    join(second, doctor, monday)
    cancel_as_patient(site, a, doctor, monday, "09:00")
    assert owner_of(site, doctor, monday, "09:00") == (first.user_id, "waitlist")
    page = first.page("/appointments")
    assert 'class="badge"' in page and "You have 1 new message" in page
    assert "a spot opened up" in first.page("/messages")
    assert "#1" in second.page("/appointments")  # moved up


def test_opening_messages_marks_them_read_but_keeps_them(site, monday):
    doctor, a, _ = full_day(site, monday)
    first = site.patient(1)
    join(first, doctor, monday)
    cancel_as_patient(site, a, doctor, monday, "09:00")
    assert "New</span>" in first.page("/messages")
    page = first.page("/messages")
    assert "a spot opened up" in page and "New</span>" not in page  # still listed, no longer new
    assert 'class="badge"' not in first.page("/appointments")


def test_patients_who_cannot_take_the_slot_are_skipped_but_keep_their_place(site, monday):
    doctor, a, _ = full_day(site, monday)
    busy, free = site.patient(1), site.patient(2)
    join(busy, doctor, monday)
    join(free, doctor, monday)
    site.appointment(busy.user_id, 3, monday, "09:00")  # clash: busy already has 09:00 elsewhere
    cancel_as_patient(site, a, doctor, monday, "09:00")
    assert owner_of(site, doctor, monday, "09:00") == (free.user_id, "waitlist")
    assert site.one("SELECT status FROM waitlist WHERE patient_id = ?", (busy.user_id,))["status"] == "waiting"


def test_moving_a_booking_away_also_serves_the_wait_list(site, monday):
    doctor, a, _ = full_day(site, monday)
    site.sql("INSERT INTO doctor_schedules (doctor_id, weekday, start_time, end_time) VALUES (?, ?, '14:00', '14:30')",
             (doctor, monday.weekday()))
    site.appointment(site.patient(13).user_id, doctor, monday, "14:00")
    waiting = site.patient(1)
    join(waiting, doctor, monday)
    appt = site.one("SELECT id FROM appointments WHERE doctor_id = ? AND start_time = '09:00'", (doctor,))["id"]
    wednesday = monday + timedelta(days=2)
    site.sql("INSERT INTO doctor_schedules (doctor_id, weekday, start_time, end_time) VALUES (?, ?, '09:00', '09:30')",
             (doctor, wednesday.weekday()))
    assert "Moved to" in a.text(f"/appointments/{appt}/reschedule", dict(date=wednesday.isoformat(), time="09:00"))
    assert owner_of(site, doctor, monday, "09:00") == (waiting.user_id, "waitlist")


def test_slots_starting_within_two_hours_are_not_handed_out(site):
    day, time = in_minutes(60)
    doctor = site.new_doctor()
    site.sql("INSERT INTO waitlist (patient_id, doctor_id, wait_date) VALUES (?, ?, ?)",
             (site.patient(1).user_id, doctor, day.isoformat()))
    with site.app.app_context():
        import appointments
        assert appointments.promote_waitlist(doctor, day.isoformat(), time) is None


def test_clinic_cancellation_notifies_the_patient_and_fills_the_slot(site, monday):
    doctor, a, _ = full_day(site, monday)
    waiting = site.patient(1)
    join(waiting, doctor, monday)
    appt = site.one("SELECT id FROM appointments WHERE doctor_id = ? AND start_time = '09:00'", (doctor,))["id"]
    page = site.admin().text(f"/admin/appointments/{appt}/cancel", from_page=f"/admin/dashboard?date={monday}")
    assert "went to Patient 1 from the wait list" in page
    assert "The clinic cancelled" in a.page("/messages")
    assert site.one("SELECT cancelled_by FROM appointments WHERE id = ?", (appt,))["cancelled_by"] == "clinic"


def test_booking_directly_takes_you_off_that_days_wait_list(site, monday):
    doctor, a, _ = full_day(site, monday)
    waiting = site.patient(1)
    join(waiting, doctor, monday)
    site.sql("UPDATE appointments SET status = 'cancelled' WHERE patient_id = ?", (a.user_id,))  # no promotion
    waiting.text("/book", dict(doctor_id=doctor, date=monday.isoformat(), time="09:00"), from_page="/book")
    assert site.one("SELECT status FROM waitlist")["status"] == "booked"


def test_leaving_the_wait_list(site, monday):
    doctor, _, _ = full_day(site, monday)
    b = site.patient(1)
    join(b, doctor, monday)
    entry = site.one("SELECT id FROM waitlist")["id"]
    assert "left the wait list" in b.text(f"/waitlist/{entry}/leave", from_page="/appointments")
    assert "Wait lists you" not in b.page("/appointments")


def test_at_most_three_wait_lists(site):
    b = site.patient(1)
    days = [date.today() + timedelta(days=n) for n in (3, 4, 5, 6)]
    doctors = []
    for i, day in enumerate(days):
        did = site.sql("INSERT INTO doctors (full_name, email, specialty, department) VALUES (?, ?, 'T', 'T')",
                       (f"Dr. {i}", f"d{i}@torontomu.ca"))
        site.sql("INSERT INTO doctor_schedules (doctor_id, weekday, start_time, end_time) VALUES (?, ?, '09:00', '09:30')",
                 (did, day.weekday()))
        site.appointment(site.patient(20 + i).user_id, did, day, "09:00")
        doctors.append(did)
    for did, day in list(zip(doctors, days))[:3]:
        assert "on the wait list" in join(b, did, day)
    assert "up to 3 wait lists" in join(b, doctors[3], days[3])


def test_old_wait_list_entries_expire(site):
    site.sql("INSERT INTO waitlist (patient_id, doctor_id, wait_date) VALUES (?, 1, ?)",
             (site.patient(1).user_id, (date.today() - timedelta(days=1)).isoformat()))
    site.admin().page("/admin/dashboard")
    assert site.one("SELECT status FROM waitlist")["status"] == "expired"


def test_no_wait_list_for_a_day_that_is_already_over(site):
    """Sprint 4 bug fix: you could join the wait list for a day whose hours had ended."""
    day, _ = in_minutes(0)
    doctor = site.new_doctor(slots_on=day, start="00:00", end="00:30")
    site.appointment(site.patient(11).user_id, doctor, day, "00:00")
    b = site.patient(1)
    assert "no time left that day" in join(b, doctor, day)
    assert "Join wait list" not in b.page(f"/book?date={day}&specialty=Testing")


def test_new_hours_go_to_the_wait_list_first(site, monday):
    """Sprint 4 bug fix: hours added to a full day sat empty while patients waited."""
    doctor, _, _ = full_day(site, monday)
    waiting = site.patient(1)
    join(waiting, doctor, monday)
    uid = site.make_user("Dr. Test Doctor", "test.doctor@torontomu.ca", "doctor")
    site.sql("UPDATE doctors SET user_id = ? WHERE id = ?", (uid, doctor))
    page = site.browser("test.doctor@torontomu.ca").text(
        "/doctor/hours", dict(action="add", weekday=monday.weekday(), start_time="11:00", end_time="11:30"))
    assert "1 patient(s) from the wait list were booked" in page
    assert owner_of(site, doctor, monday, "11:00") == (waiting.user_id, "waitlist")
