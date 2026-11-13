# TMU Health Booking

A clinic appointment system for Toronto Metropolitan University students, built in four sprints. Each sprint is a complete, runnable copy of the app in its own folder, so you can see how it grew.

| Folder | Sprint | Weeks | What it adds |
|---|---|---|---|
| [`sprint-1`](sprint-1) | 1 | 3–5 | Authentication, patient and admin login, simple booking, simple admin dashboard |
| [`sprint-2`](sprint-2) | 2 | 6–8 | Doctor availability page, full appointment booking |
| [`sprint-3`](sprint-3) | 3 | 9–10 | Wait list with automatic booking, doctor login and dashboard, full admin dashboard, walk-in queue |
| [`sprint-4`](sprint-4) | 4 | 11–12 | Email notifications, patient message center, 94 automated tests, bug fixes, final improvements. **This is the final version.** |

To run the final version:

```bash
cd sprint-4
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
flask --app app seed-demo
flask --app app run --debug
```

Then open http://127.0.0.1:5000 and log in as `frontdesk@torontomu.ca`, `priya.raman@torontomu.ca` or `sam.lee@torontomu.ca`, all with the password `password123`. See [`sprint-4/README.md`](sprint-4/README.md) for details.
