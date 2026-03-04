import os
import uuid
import pytz
import requests
import psycopg2
import smtplib
from email.mime.text import MIMEText
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# -------------------------------
# DATABASE CONNECTION
# -------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# -------------------------------
# CREATE TABLES
# -------------------------------

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

cur.execute("""
CREATE TABLE IF NOT EXISTS leads (
    lead_id VARCHAR(20) PRIMARY KEY,
    business_name VARCHAR(150),
    owner_name VARCHAR(150),
    phone VARCHAR(30),
    interest_level VARCHAR(20),
    notes TEXT,
    created_at TIMESTAMP
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS demos (
    demo_id VARCHAR(20) PRIMARY KEY,
    name VARCHAR(150),
    email VARCHAR(150),
    date VARCHAR(20),
    time VARCHAR(10),
    created_at TIMESTAMP
);
""")

conn.commit()

# -------------------------------
# EMAIL CONFIG
# -------------------------------

EMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
EMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")

def send_email(to_email, subject, html_content):

    msg = MIMEText(html_content, "html")
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_email

    try:
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, to_email, msg.as_string())
        server.quit()
    except:
        pass

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


class RescheduleRequest(BaseModel):
    appointment_id: str
    new_date: str
    new_time: str


class Lead(BaseModel):
    business_name: str
    owner_name: str
    phone: str
    interest_level: str
    notes: str


class Demo(BaseModel):
    name: str
    email: str
    date: str
    time: str


# -------------------------------
# ROOT
# -------------------------------

@app.get("/")
def root():
    return {"success": True, "message": "VoxDesk Backend Running"}

# -------------------------------
# CURRENT DATE TIME
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

    cur.execute("""
        SELECT * FROM appointments
        WHERE doctor_name = %s
        AND date = %s
        AND time = %s
        AND status = 'Confirmed'
    """, (
        appointment.doctor_name.strip(),
        appointment.date.strip(),
        appointment.time.strip()
    ))

    existing = cur.fetchone()

    if existing:
        return {
            "success": False,
            "message": f"Sorry, Dr. {appointment.doctor_name} is already booked on {appointment.date} at {appointment.time}."
        }

    appointment_id = "DH" + str(uuid.uuid4())[:5].upper()

    cur.execute("""
        INSERT INTO appointments
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        appointment_id,
        appointment.patient_name,
        appointment.email,
        appointment.phone,
        appointment.doctor_name,
        appointment.date,
        appointment.time,
        "Confirmed"
    ))

    conn.commit()

    # EMAIL CONFIRMATION
    html = f"""
    <h2>Dubai Hospital Appointment Confirmation</h2>
    <p>Your appointment has been confirmed.</p>
    <p><b>Doctor:</b> {appointment.doctor_name}</p>
    <p><b>Date:</b> {appointment.date}</p>
    <p><b>Time:</b> {appointment.time}</p>
    <p><b>Appointment ID:</b> {appointment_id}</p>
    """

    send_email(appointment.email, "Appointment Confirmation", html)

    return {
        "success": True,
        "message": f"Your appointment with Dr. {appointment.doctor_name} on {appointment.date} at {appointment.time} is confirmed. Your appointment ID is {appointment_id}."
    }

# -------------------------------
# CANCEL APPOINTMENT
# -------------------------------

@app.post("/cancel-appointment")
def cancel_appointment(request: CancelRequest):

    appointment_id = request.appointment_id.strip().upper()

    cur.execute("""
        UPDATE appointments
        SET status = 'Cancelled'
        WHERE appointment_id = %s
        RETURNING *
    """, (appointment_id,))

    updated = cur.fetchone()
    conn.commit()

    if updated:
        return {
            "success": True,
            "message": f"Appointment {appointment_id} has been cancelled."
        }

    return {"success": False, "message": "Appointment ID not found"}

# -------------------------------
# RESCHEDULE
# -------------------------------

@app.post("/reschedule-appointment")
def reschedule_appointment(request: RescheduleRequest):

    appointment_id = request.appointment_id.strip().upper()

    cur.execute("""
        UPDATE appointments
        SET date = %s, time = %s
        WHERE appointment_id = %s
        RETURNING *
    """, (
        request.new_date,
        request.new_time,
        appointment_id
    ))

    updated = cur.fetchone()
    conn.commit()

    if updated:
        return {
            "success": True,
            "message": f"Appointment {appointment_id} rescheduled to {request.new_date} at {request.new_time}."
        }

    return {"success": False, "message": "Appointment ID not found"}

# -------------------------------
# SAVE LEAD (OUTBOUND SALES)
# -------------------------------

@app.post("/save-lead")
def save_lead(lead: Lead):

    lead_id = "LD" + str(uuid.uuid4())[:6].upper()

    cur.execute("""
        INSERT INTO leads
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (
        lead_id,
        lead.business_name,
        lead.owner_name,
        lead.phone,
        lead.interest_level,
        lead.notes,
        datetime.utcnow()
    ))

    conn.commit()

    return {
        "success": True,
        "message": "Lead saved successfully"
    }

# -------------------------------
# BOOK DEMO (OUTBOUND SALES)
# -------------------------------

@app.post("/book-demo")
def book_demo(demo: Demo):

    demo_id = "DM" + str(uuid.uuid4())[:6].upper()

    cur.execute("""
        INSERT INTO demos
        VALUES (%s,%s,%s,%s,%s,%s)
    """, (
        demo_id,
        demo.name,
        demo.email,
        demo.date,
        demo.time,
        datetime.utcnow()
    ))

    conn.commit()

    # SEND DEMO EMAIL

    html = f"""
    <h2>VoxDesk Demo Scheduled</h2>
    <p>Your demo has been scheduled.</p>
    <p><b>Date:</b> {demo.date}</p>
    <p><b>Time:</b> {demo.time}</p>
    <p>We look forward to showing you how VoxDesk can automate your calls.</p>
    """

    send_email(demo.email, "VoxDesk Demo Confirmation", html)

    return {
        "success": True,
        "message": "Demo booked successfully"
    }

# -------------------------------
# ADMIN DASHBOARD
# -------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):

    cur.execute("SELECT * FROM appointments ORDER BY date,time")
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