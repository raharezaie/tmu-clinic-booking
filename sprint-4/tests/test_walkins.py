"""Walk-in queue: front desk form, queue order, doctors calling patients in."""
from datetime import date


def add(desk, **form):
    data = dict(patient_name="Alex Kim", reason="Sore throat", urgency="normal")
    data.update(form)
    return desk.text("/walk-ins/", data)


def works_today(site, doctor_id):
    if not site.one("SELECT 1 FROM doctor_schedules WHERE doctor_id = ? AND weekday = ?",
                    (doctor_id, date.today().weekday())):
        site.sql("INSERT INTO doctor_schedules (doctor_id, weekday, start_time, end_time) VALUES (?, ?, '07:00', '20:00')",
                 (doctor_id, date.today().weekday()))


def entry(site, name):
    return site.one("SELECT * FROM walk_ins WHERE patient_name = ?", (name,))


def test_only_the_front_desk_uses_the_walk_in_form(site):
    assert site.patient().get("/walk-ins/").status_code == 403
    assert site.doctor().get("/walk-ins/").status_code == 403
    assert "Add a walk-in" in site.admin().page("/walk-ins/")


def test_form_requires_name_and_reason(site):
    page = add(site.admin(), patient_name="", reason="", student_id="12")
    assert "Enter the patient" in page and "Enter the reason" in page and "9 digits" in page


def test_cannot_ask_for_a_doctor_who_is_off_today(site):
    off = site.one("SELECT d.id FROM doctors d WHERE NOT EXISTS (SELECT 1 FROM doctor_schedules s "
                   "WHERE s.doctor_id = d.id AND s.weekday = ?)", (date.today().weekday(),))
    if off is None:
        off_id = site.new_doctor()
    else:
        off_id = off["id"]
    assert "isn&#39;t working today" in add(site.admin(), preferred_doctor_id=off_id)


def test_urgent_walk_ins_go_to_the_front(site):
    desk = site.admin()
    add(desk, patient_name="Alex Kim")
    add(desk, patient_name="Bea Lin", urgency="urgent")
    add(desk, patient_name="Cy Roy")
    page = desk.page("/walk-ins/")
    assert page.index("Bea Lin") < page.index("Alex Kim") < page.index("Cy Roy")


def test_student_number_links_the_walk_in_to_their_account(site):
    patient = site.patient(1)
    add(site.admin(), student_id="500000001")
    assert entry(site, "Alex Kim")["patient_id"] == patient.user_id
    assert "(has an account)" in site.admin().page("/walk-ins/")


def test_doctor_calls_next_urgent_first_and_respects_requests(site):
    works_today(site, 1)
    works_today(site, 3)
    desk = site.admin()
    add(desk, patient_name="Wants Bello", preferred_doctor_id=3)
    add(desk, patient_name="Anyone")
    add(desk, patient_name="Urgent", urgency="urgent")
    raman = site.doctor(1)
    assert "Called in Urgent (urgent)" in raman.text("/doctor/walk-ins/call-next", from_page="/doctor/dashboard")
    raman.text(f"/doctor/walk-ins/{entry(site, 'Urgent')['id']}/done", from_page="/doctor/dashboard")
    assert "Called in Anyone" in raman.text("/doctor/walk-ins/call-next", from_page="/doctor/dashboard")
    assert "No walk-ins are waiting for you" in raman.text("/doctor/walk-ins/call-next", from_page="/doctor/dashboard")
    assert "Called in Wants Bello" in site.doctor(3).text("/doctor/walk-ins/call-next", from_page="/doctor/dashboard")


def test_front_desk_sends_in_and_finishes_walk_ins(site):
    works_today(site, 1)
    desk = site.admin()
    add(desk, patient_name="Alex Kim")
    add(desk, patient_name="Bea Lin")
    alex, bea = entry(site, "Alex Kim")["id"], entry(site, "Bea Lin")["id"]
    assert "sent in" in desk.text(f"/walk-ins/{alex}/assign", dict(doctor_id=1), from_page="/walk-ins/")
    assert "isn&#39;t waiting" in desk.text(f"/walk-ins/{alex}/assign", dict(doctor_id=1), from_page="/walk-ins/")
    assert "Only patients who are still waiting" in desk.text(f"/walk-ins/{alex}/status", dict(status="left"),
                                                              from_page="/walk-ins/")
    assert "marked as done" in desk.text(f"/walk-ins/{alex}/status", dict(status="done"), from_page="/walk-ins/")
    assert "marked as left" in desk.text(f"/walk-ins/{bea}/status", dict(status="left"), from_page="/walk-ins/")
    assert "Finished today (2)" in desk.page("/walk-ins/")


def test_walk_in_who_asked_for_a_doctor_cannot_be_sent_to_another(site):
    works_today(site, 1)
    works_today(site, 3)
    desk = site.admin()
    add(desk, preferred_doctor_id=3)
    page = desk.text(f"/walk-ins/{entry(site, 'Alex Kim')['id']}/assign", dict(doctor_id=1), from_page="/walk-ins/")
    assert "asked for a different doctor" in page


def test_doctors_only_finish_their_own_walk_ins(site):
    works_today(site, 1)
    add(site.admin())
    site.doctor(1).text("/doctor/walk-ins/call-next", from_page="/doctor/dashboard")
    alex = entry(site, "Alex Kim")["id"]
    assert site.doctor(3).post(f"/doctor/walk-ins/{alex}/done", from_page="/doctor/dashboard",
                               follow=False).status_code == 404


def test_dashboard_shows_the_queue(site):
    add(site.admin(), patient_name="Elle Moreau", urgency="urgent")
    page = site.admin().page("/admin/dashboard")
    assert "Elle Moreau" in page and "#1 urgent" in page
