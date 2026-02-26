from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uuid
from datetime import datetime
import pytz
import requests
import os
import psycopg2

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# -------------------------------
# DATABASE CONNECTION
# -------------------------------

DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# Create table if not exists
cur.execute("""
CREATE TABLE IF NOT EXISTS appointments (
    appointment_id VARCHAR(20) PRIMARY KEY,
    patient_name VARCHAR(100),
    doctor_name VARCHAR(50),
    date VARCHAR(20),
    time VARCHAR(10)
);
""")
conn.commit()

# 24-hour schedule
doctor_schedule = {
    "ahmed": ["09:00", "10:00", "11:00"],
    "sara": ["13:00", "14:00", "15:00"]
}

# -------------------------------
# MODELS
# -------------------------------

class Appointment(BaseModel):
    patient_name: str
    doctor_name: str
    date: str
    time: str


class CancelRequest(BaseModel):
    appointment_id: str


# -------------------------------
# ROOT
# -------------------------------

@app.get("/")
def root():
    return {"success": True, "message": "Dubai Hospital Backend Running"}


# -------------------------------
# BOOK APPOINTMENT
# -------------------------------

@app.post("/book-appointment")
def book_appointment(appointment: Appointment):

    appointment_id = "APT" + str(uuid.uuid4())[:6].upper()

    cur.execute(
        "INSERT INTO appointments VALUES (%s, %s, %s, %s, %s)",
        (
            appointment_id,
            appointment.patient_name.strip(),
            appointment.doctor_name.strip(),
            appointment.date.strip(),
            appointment.time.strip(),
        )
    )
    conn.commit()

    new_appt = {
        "appointment_id": appointment_id,
        "patient_name": appointment.patient_name,
        "doctor_name": appointment.doctor_name,
        "date": appointment.date,
        "time": appointment.time
    }

    # Send to Make
    try:
        requests.post(
            "https://hook.us2.make.com/dbox8aiyjv3ip5gup7vrbac6dmi9jfzg",
            json=new_appt,
            timeout=5
        )
    except:
        pass

    return {
        "success": True,
        "message": f"Your appointment is confirmed. Your ID is {appointment_id}.",
        "data": new_appt
    }


# -------------------------------
# CANCEL APPOINTMENT
# -------------------------------

@app.post("/cancel-appointment")
def cancel_appointment(request: CancelRequest):

    cur.execute(
        "DELETE FROM appointments WHERE appointment_id = %s RETURNING *",
        (request.appointment_id.strip().upper(),)
    )
    deleted = cur.fetchone()
    conn.commit()

    if deleted:
        return {
            "success": True,
            "message": f"Appointment {request.appointment_id} cancelled successfully."
        }

    return {"success": False, "message": "Appointment ID not found"}


# -------------------------------
# ADMIN DASHBOARD
# -------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):

    cur.execute("SELECT * FROM appointments ORDER BY date, time;")
    rows = cur.fetchall()

    appointments = []
    for row in rows:
        appointments.append({
            "appointment_id": row[0],
            "patient_name": row[1],
            "doctor_name": row[2],
            "date": row[3],
            "time": row[4],
        })

    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "appointments": appointments}
    )