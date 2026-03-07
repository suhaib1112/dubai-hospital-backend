import os
import uuid
import pytz
import psycopg2
import smtplib
import threading
import logging
import secrets

from contextlib import contextmanager
from datetime import datetime
from email.mime.text import MIMEText

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel


# -----------------------------
# LOGGING SETUP
# -----------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("voxdesk")


# -----------------------------
# APP INITIALIZATION
# -----------------------------

app = FastAPI(docs_url=None, redoc_url=None)  # Swagger hidden in production
templates = Jinja2Templates(directory="templates")
security = HTTPBasic()


# -----------------------------
# DATABASE CONNECTION
# -----------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")

@contextmanager
def get_db():
    """
    Context manager for DB connections.
    Automatically closes the connection even if an error occurs.
    Usage: with get_db() as (conn, cur):
    """
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        cur = conn.cursor()
        yield conn, cur
    except psycopg2.Error as e:
        logger.error(f"Database connection error: {e}")
        raise
    finally:
        if conn:
            conn.close()


# -----------------------------
# CREATE TABLES
# -----------------------------

def create_tables():
    try:
        with get_db() as (conn, cur):
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
            logger.info("Tables created / verified successfully")

    except Exception as e:
        logger.error(f"Failed to create tables: {e}")

create_tables()


# -----------------------------
# EMAIL CONFIG
# -----------------------------

EMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
EMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")

def send_email(to_email: str, subject: str, html: str):
    """Send HTML email. Logs success or failure — never silently fails."""
    try:
        msg = MIMEText(html, "html")
        msg["Subject"] = subject
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = to_email

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, to_email, msg.as_string())

        logger.info(f"Email sent to {to_email} | Subject: {subject}")

    except smtplib.SMTPException as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
    except Exception as e:
        logger.error(f"Unexpected email error: {e}")


# -----------------------------
# ADMIN AUTH
# -----------------------------

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """
    Protects admin routes with a username/password.
    Set ADMIN_USERNAME and ADMIN_PASSWORD in your Render environment variables.
    """
    correct_user = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_pass = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)

    if not (correct_user and correct_pass):
        logger.warning(f"Failed admin login attempt: username='{credentials.username}'")
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# -----------------------------
# MODELS
# -----------------------------

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


# -----------------------------
# ROOT
# -----------------------------

@app.get("/")
def root():
    return {"success": True, "message": "VoxDesk Backend Running"}


# -----------------------------
# CURRENT DATE TIME
# -----------------------------

@app.get("/get-current-datetime")
def get_datetime():
    dubai = pytz.timezone("Asia/Dubai")
    now = datetime.now(dubai)

    return {
        "success": True,
        "date": now.strftime("%d/%m/%Y"),
        "time": now.strftime("%H:%M"),
        "day": now.strftime("%A")
    }


# -----------------------------
# BOOK APPOINTMENT
# -----------------------------

@app.post("/book-appointment")
def book_appointment(appointment: Appointment):
    try:
        with get_db() as (conn, cur):

            cur.execute("""
                SELECT * FROM appointments
                WHERE doctor_name=%s AND date=%s AND time=%s AND status='Confirmed'
            """, (appointment.doctor_name, appointment.date, appointment.time))

            if cur.fetchone():
                return {
                    "success": False,
                    "message": f"Dr. {appointment.doctor_name} is already booked at that time."
                }

            appointment_id = "APT" + str(uuid.uuid4())[:6].upper()

            cur.execute("""
                INSERT INTO appointments VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
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
            logger.info(f"Appointment booked: {appointment_id} | {appointment.patient_name} | Dr. {appointment.doctor_name}")

        html = f"""
        <h2>Appointment Confirmed ✅</h2>
        <p><strong>Doctor:</strong> {appointment.doctor_name}</p>
        <p><strong>Date:</strong> {appointment.date}</p>
        <p><strong>Time:</strong> {appointment.time}</p>
        <p><strong>Appointment ID:</strong> {appointment_id}</p>
        """

        threading.Thread(
            target=send_email,
            args=(appointment.email, "Appointment Confirmation", html)
        ).start()

        return {
            "success": True,
            "message": f"Appointment confirmed. ID: {appointment_id}"
        }

    except Exception as e:
        logger.error(f"Error booking appointment: {e}")
        return {"success": False, "message": "Something went wrong. Please try again."}


# -----------------------------
# CANCEL APPOINTMENT
# -----------------------------

@app.post("/cancel-appointment")
def cancel_appointment(request: CancelRequest):
    try:
        with get_db() as (conn, cur):

            cur.execute("""
                UPDATE appointments
                SET status='Cancelled'
                WHERE appointment_id=%s
                RETURNING *
            """, (request.appointment_id.upper(),))

            updated = cur.fetchone()
            conn.commit()

        if updated:
            logger.info(f"Appointment cancelled: {request.appointment_id}")
            return {"success": True, "message": "Appointment cancelled"}

        return {"success": False, "message": "Appointment not found"}

    except Exception as e:
        logger.error(f"Error cancelling appointment {request.appointment_id}: {e}")
        return {"success": False, "message": "Something went wrong. Please try again."}


# -----------------------------
# RESCHEDULE APPOINTMENT
# -----------------------------

@app.post("/reschedule-appointment")
def reschedule(request: RescheduleRequest):
    try:
        with get_db() as (conn, cur):

            cur.execute("""
                UPDATE appointments
                SET date=%s, time=%s
                WHERE appointment_id=%s
                RETURNING *
            """, (request.new_date, request.new_time, request.appointment_id))

            updated = cur.fetchone()
            conn.commit()

        if updated:
            logger.info(f"Appointment rescheduled: {request.appointment_id} → {request.new_date} {request.new_time}")
            return {"success": True, "message": "Appointment rescheduled"}

        return {"success": False, "message": "Appointment not found"}

    except Exception as e:
        logger.error(f"Error rescheduling appointment {request.appointment_id}: {e}")
        return {"success": False, "message": "Something went wrong. Please try again."}


# -----------------------------
# SAVE LEAD
# -----------------------------

@app.post("/save-lead")
def save_lead(lead: Lead):
    try:
        with get_db() as (conn, cur):

            lead_id = "LD" + str(uuid.uuid4())[:6].upper()

            cur.execute("""
                INSERT INTO leads VALUES (%s,%s,%s,%s,%s,%s,%s)
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
            logger.info(f"Lead saved: {lead_id} | {lead.business_name}")

        return {"success": True, "message": "Lead saved"}

    except Exception as e:
        logger.error(f"Error saving lead: {e}")
        return {"success": False, "message": "Something went wrong. Please try again."}


# -----------------------------
# BOOK DEMO
# -----------------------------

@app.post("/book-demo")
def book_demo(demo: Demo):
    try:
        with get_db() as (conn, cur):

            demo_id = "DM" + str(uuid.uuid4())[:6].upper()

            cur.execute("""
                INSERT INTO demos VALUES (%s,%s,%s,%s,%s,%s)
            """, (
                demo_id,
                demo.name,
                demo.email,
                demo.date,
                demo.time,
                datetime.utcnow()
            ))

            conn.commit()
            logger.info(f"Demo booked: {demo_id} | {demo.name} | {demo.email}")

        html = f"""
        <h2>VoxDesk Demo Scheduled ✅</h2>
        <p><strong>Name:</strong> {demo.name}</p>
        <p><strong>Date:</strong> {demo.date}</p>
        <p><strong>Time:</strong> {demo.time}</p>
        <p>We'll see you then!</p>
        """

        threading.Thread(
            target=send_email,
            args=(demo.email, "VoxDesk Demo Confirmation", html)
        ).start()

        return {"success": True, "message": "Demo booked"}

    except Exception as e:
        logger.error(f"Error booking demo: {e}")
        return {"success": False, "message": "Something went wrong. Please try again."}


# -----------------------------
# ADMIN APPOINTMENTS
# -----------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, username: str = Depends(verify_admin)):
    try:
        with get_db() as (conn, cur):
            cur.execute("SELECT * FROM appointments ORDER BY date, time")
            rows = cur.fetchall()

        appointments = [
            {
                "appointment_id": r[0],
                "patient_name": r[1],
                "email": r[2],
                "phone": r[3],
                "doctor_name": r[4],
                "date": r[5],
                "time": r[6],
                "status": r[7]
            }
            for r in rows
        ]

        return templates.TemplateResponse(
            "admin.html",
            {"request": request, "appointments": appointments}
        )

    except Exception as e:
        logger.error(f"Error loading admin dashboard: {e}")
        return HTMLResponse("<h1>Error loading dashboard</h1>", status_code=500)


# -----------------------------
# ADMIN VOXDESK (private sales dashboard)
# -----------------------------

@app.get("/admin-voxdesk", response_class=HTMLResponse)
def admin_voxdesk(request: Request, username: str = Depends(verify_admin)):
    try:
        return templates.TemplateResponse("admin_sales.html", {"request": request})
    except Exception as e:
        logger.error(f"Error loading sales dashboard: {e}")
        return HTMLResponse("<h1>Error loading dashboard</h1>", status_code=500)


# -----------------------------
# ADMIN LEADS
# -----------------------------

@app.get("/admin-leads")
def admin_leads(username: str = Depends(verify_admin)):
    try:
        with get_db() as (conn, cur):
            cur.execute("SELECT * FROM leads ORDER BY created_at DESC")
            rows = cur.fetchall()

        return {"leads": [
            [r[0], r[1], r[2], r[3], r[4], r[5], r[6].isoformat() if r[6] else None]
            for r in rows
        ]}

    except Exception as e:
        logger.error(f"Error loading leads: {e}")
        return {"leads": []}


# -----------------------------
# ADMIN DEMOS
# -----------------------------

@app.get("/admin-demos")
def admin_demos(username: str = Depends(verify_admin)):
    try:
        with get_db() as (conn, cur):
            cur.execute("SELECT * FROM demos ORDER BY created_at DESC")
            rows = cur.fetchall()

        return {"demos": [
            [r[0], r[1], r[2], r[3], r[4], r[5].isoformat() if r[5] else None]
            for r in rows
        ]}

    except Exception as e:
        logger.error(f"Error loading demos: {e}")
        return {"demos": []}