"""1.0 Authenticate User: registration, login, roles, security."""
from conftest import PASSWORD


def register(b, **over):
    data = dict(full_name="Sam Lee", email="sam@torontomu.ca", student_id="501234567",
                password=PASSWORD, confirm=PASSWORD)
    data.update(over)
    return b.text("/register", data)


def test_patient_can_register_and_log_in(site):
    b = site.browser()
    assert "Account created" in register(b)
    page = b.login("SAM@TorontoMU.ca")  # email is not case-sensitive
    assert "My appointments" in page and "Sam Lee" in page


def test_registration_rules_all_reported_at_once(site):
    page = register(site.browser(), full_name="", email="sam@gmail.com", student_id="123",
                    password="short", confirm="other")
    for msg in ("Enter your full name", "@torontomu.ca", "9 digits", "at least 8 characters", "don&#39;t match"):
        assert msg in page


def test_duplicate_email_is_refused(site):
    b = site.browser()
    register(b)
    assert "already exists" in register(b, student_id="509999999")


def test_duplicate_student_number_is_refused(site):
    """Sprint 4 bug fix: two accounts could share one student number."""
    b = site.browser()
    register(b)
    assert "student number already has an account" in register(b, email="other@torontomu.ca")


def test_wrong_password_is_rejected_with_a_generic_message(site):
    site.make_user("Sam", "sam@torontomu.ca")
    assert "Email or password is incorrect" in site.browser().login("sam@torontomu.ca", "wrongpass1")
    assert "Email or password is incorrect" in site.browser().login("nobody@torontomu.ca", "wrongpass1")


def test_account_locks_after_five_wrong_passwords(site):
    """Sprint 4 improvement: stop password guessing."""
    site.make_user("Sam", "sam@torontomu.ca")
    b = site.browser()
    for _ in range(4):
        assert "incorrect" in b.login("sam@torontomu.ca", "wrongpass1")
    assert "locked for 15 minutes" in b.login("sam@torontomu.ca", "wrongpass1")
    assert "Try again in" in b.login("sam@torontomu.ca")  # even the right password is refused
    site.sql("UPDATE users SET locked_until = '2000-01-01T00:00:00' WHERE email = 'sam@torontomu.ca'")
    assert "My appointments" in b.login("sam@torontomu.ca")


def test_successful_login_resets_the_failed_count(site):
    site.make_user("Sam", "sam@torontomu.ca")
    b = site.browser()
    for _ in range(4):
        b.login("sam@torontomu.ca", "wrongpass1")
    b.login("sam@torontomu.ca")
    assert site.one("SELECT failed_logins FROM users WHERE email = 'sam@torontomu.ca'")["failed_logins"] == 0


def test_login_returns_to_the_requested_page_but_never_another_site(site):
    site.make_user("Sam", "sam@torontomu.ca")
    b = site.browser()
    r = b.client.get("/book")
    assert r.status_code == 302 and "/login?next=/book" in r.headers["Location"]
    r = b.post("/login?next=/book", dict(email="sam@torontomu.ca", password=PASSWORD), from_page="/login", follow=False)
    assert r.headers["Location"] == "/book"
    for evil in ("//evil.com", "https://evil.com", "/\\evil.com"):
        b = site.browser()
        r = b.post(f"/login?next={evil}", dict(email="sam@torontomu.ca", password=PASSWORD),
                   from_page="/login", follow=False)
        assert "evil" not in r.headers["Location"]


def test_each_role_only_reaches_its_own_pages(site):
    patient, admin, doctor = site.patient(), site.admin(), site.doctor()
    assert patient.get("/admin/dashboard").status_code == 403
    assert patient.get("/doctor/dashboard").status_code == 403
    assert patient.get("/walk-ins/").status_code == 403
    assert admin.get("/book").status_code == 403
    assert admin.get("/doctor/dashboard").status_code == 403
    assert doctor.get("/book").status_code == 403
    assert doctor.get("/admin/dashboard").status_code == 403
    assert site.browser().get("/admin/dashboard").status_code == 302  # not logged in: sent to login


def test_forms_without_csrf_token_are_rejected(site):
    b = site.patient()
    assert b.client.post("/book", data={"doctor_id": 1}).status_code == 400


def test_logout_only_works_as_a_form_post(site):
    b = site.patient()
    assert b.get("/logout").status_code == 405
    assert "logged out" in b.text("/logout", from_page="/appointments")
    assert b.get("/appointments").status_code == 302


def test_admin_needs_the_staff_invite_code(site):
    b = site.browser()
    data = dict(full_name="Desk", email="desk@torontomu.ca", password=PASSWORD, confirm=PASSWORD)
    assert "invite code is incorrect" in b.text("/admin/register", dict(data, invite_code="guess"))
    assert "Staff account created" in b.text("/admin/register", dict(data, invite_code="TMU-STAFF-2026"))
    assert "Clinic summary" in b.login("desk@torontomu.ca")


class TestDoctorRegistration:
    data = dict(full_name="Dr. Priya Raman", email="priya.raman@torontomu.ca", password=PASSWORD,
                confirm=PASSWORD, invite_code="TMU-DOCTOR-2026")

    def test_needs_the_doctor_invite_code(self, site):
        assert "Doctor invite code is incorrect" in site.browser().text("/doctor/register",
                                                                          dict(self.data, invite_code="nope"))

    def test_claims_existing_profile_by_email(self, site):
        b = site.browser()
        assert "linked to your existing profile" in b.text("/doctor/register", self.data)
        assert site.one("SELECT user_id FROM doctors WHERE id = 1")["user_id"] is not None
        page = b.login("priya.raman@torontomu.ca")
        assert "Dr. Priya Raman" in page and "General Practice" in page

    def test_profile_can_only_be_claimed_once(self, site):
        site.browser().text("/doctor/register", self.data)
        assert "already has an account" in site.browser().text("/doctor/register", self.data)

    def test_new_doctor_needs_specialty_and_gets_a_profile(self, site):
        b = site.browser()
        new = dict(self.data, full_name="Dr. Nina Park", email="nina.park@torontomu.ca")
        assert "Enter your specialty" in b.text("/doctor/register", new)
        assert "add your weekly hours" in b.text("/doctor/register",
                                                  dict(new, specialty="Dermatology", department="Skin Clinic"))
        doc = site.one("SELECT * FROM doctors WHERE email = 'nina.park@torontomu.ca'")
        assert doc["specialty"] == "Dermatology" and doc["user_id"]
