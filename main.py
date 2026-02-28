import os
import uuid
import pytz
import psycopg2
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI()
templates = Jinja2Templates(directory="templates")

DATABASE_URL = os.environ.get("DATABASE_URL")

# -------------------------------
# CREATE TABLE (SAFE)
# -------------------------------
def init_db():
    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
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

init_db()

# -------------------------------
# EMAIL FUNCTION
# -------------------------------
def send_confirmation_email(to_email, patient_name, doctor, date, time, appointment_id):

    EMAIL_USER = os.environ.get("EMAIL_ADDRESS")
    EMAIL_PASS = os.environ.get("EMAIL_PASSWORD")

    if not EMAIL_USER or not EMAIL_PASS:
        return

    subject = "Dubai Hospital - Appointment Confirmation"

    html = f"""
    <html>
    <body style="font-family: Arial; background:#f4f6f8; padding:20px;">
        <div style="max-width:600px; margin:auto; background:white; padding:30px; border-radius:10px;">
            <h2 style="color:#0a7cff;">Dubai Hospital</h2>
            <h3>Appointment Confirmation</h3>
            <p>Hello <strong>{patient_name}</strong>,</p>
            <p>Your appointment has been successfully confirmed.</p>
            <p><strong>Doctor:</strong> Dr. {doctor}</p>
            <p><strong>Date:</strong> {date}</p>
            <p><strong>Time:</strong> {time}</p>
            <p><strong>Appointment ID:</strong> {appointment_id}</p>
            <p>Thank you for choosing Dubai Hospital.</p>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart("alternative")
    msg["From"] = EMAIL_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=10)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(EMAIL_USER, to_email, msg.as_string())
        server.quit()
    except Exception as e:
        print("EMAIL ERROR:", str(e))

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
# BOOK APPOINTMENT
# -------------------------------
@app.post("/book-appointment")
def book_appointment(appointment: Appointment):

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:

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

            if cur.fetchone():
                return {
                    "success": False,
                    "message": f"Sorry, Dr. {appointment.doctor_name} is already booked on {appointment.date} at {appointment.time}."
                }

            appointment_id = "DH" + str(uuid.uuid4())[:5].upper()

            cur.execute("""
                INSERT INTO appointments
                (appointment_id, patient_name, email, phone, doctor_name, date, time, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                appointment_id,
                appointment.patient_name.strip(),
                appointment.email.strip(),
                appointment.phone.strip(),
                appointment.doctor_name.strip(),
                appointment.date.strip(),
                appointment.time.strip(),
                "Confirmed"
            ))

    send_confirmation_email(
        appointment.email.strip(),
        appointment.patient_name.strip(),
        appointment.doctor_name.strip(),
        appointment.date.strip(),
        appointment.time.strip(),
        appointment_id
    )

    return {
        "success": True,
        "message": f"Your appointment with Dr. {appointment.doctor_name} on {appointment.date} at {appointment.time} is confirmed. Your appointment ID is {appointment_id}."
    }

# -------------------------------
# ADMIN DASHBOARD
# -------------------------------
@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
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