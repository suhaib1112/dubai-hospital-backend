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

cur.execute("""
CREATE TABLE IF NOT EXISTS appointments (
    appointment_id VARCHAR(20) PRIMARY KEY,
    patient_name VARCHAR(100),
    email VARCHAR(150),
    phone VARCHAR(30),
    doctor_name VARCHAR(50),
    date VARCHAR(20),
    time VARCHAR(10),
    status VARCHAR(20)
);
""")
conn.commit()

# -------------------------------
# MODELS
# -------------------------------

class Appointment(BaseModel):
    patient_name: str
    email: str
    phone: str
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
# CURRENT DATE & TIME
# -------------------------------

@app.get("/get-current-datetime")
def get_current_datetime():
    dubai = pytz.timezone("Asia/Dubai")
    now = datetime.now(dubai)

    return {
        "success": True,
        "date": now.strftime("%d/%m/%Y"),
        "time": now.strftime("%H:%M"),
        "day": now.strftime("%A")
    }

# -------------------------------
# BOOK APPOINTMENT
# -------------------------------

@app.post("/book-appointment")
def book_appointment(appointment: Appointment):

    appointment_id = "DH" + str(uuid.uuid4())[:5].upper()

    cur.execute(
        """
        INSERT INTO appointments
        (appointment_id, patient_name, email, phone, doctor_name, date, time, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            appointment_id,
            appointment.patient_name.strip(),
            appointment.email.strip(),
            appointment.phone.strip(),
            appointment.doctor_name.strip(),
            appointment.date.strip(),
            appointment.time.strip(),
            "Confirmed"
        )
    )
    conn.commit()

    new_appt = {
        "appointment_id": appointment_id,
        "patient_name": appointment.patient_name,
        "email": appointment.email,
        "phone": appointment.phone,
        "doctor_name": appointment.doctor_name,
        "date": appointment.date,
        "time": appointment.time,
        "status": "Confirmed"
    }

    # Send to Make webhook
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
        """
        UPDATE appointments
        SET status = 'Cancelled'
        WHERE appointment_id = %s
        RETURNING *
        """,
        (request.appointment_id.strip().upper(),)
    )
    updated = cur.fetchone()
    conn.commit()

    if updated:
        return {
            "success": True,
            "message": f"Appointment {request.appointment_id} has been cancelled."
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
            "email": row[2],
            "phone": row[3],
            "doctor_name": row[4],
            "date": row[5],
            "time": row[6],
            "status": row[7]
        })

    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "appointments": appointments}
    )