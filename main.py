import os
import uuid
import pytz
import psycopg2
import threading
import logging
import secrets
import sendgrid

from sendgrid.helpers.mail import Mail
from contextlib import contextmanager
from datetime import datetime

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
                mood VARCHAR(50),
                pain_points TEXT,
                roi_reaction VARCHAR(100),
                objection VARCHAR(100),
                notes TEXT,
                created_at TIMESTAMP
            );
            """)
            for col, coltype in [
                ("mood", "VARCHAR(50)"),
                ("pain_points", "TEXT"),
                ("roi_reaction", "VARCHAR(100)"),
                ("objection", "VARCHAR(100)"),
            ]:
                try:
                    cur.execute(f"ALTER TABLE leads ADD COLUMN IF NOT EXISTS {col} {coltype};")
                except Exception:
                    pass

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

            cur.execute("""
            CREATE TABLE IF NOT EXISTS call_logs (
                call_id VARCHAR(20) PRIMARY KEY,
                caller_phone VARCHAR(30),
                call_duration VARCHAR(20),
                call_outcome VARCHAR(100),
                summary TEXT,
                created_at TIMESTAMP
            );
            """)

            conn.commit()
            logger.info("Tables created / verified successfully")

    except Exception as e:
        logger.error(f"Failed to create tables: {e}")

create_tables()


# -----------------------------
# EMAIL CONFIG (SendGrid)
# -----------------------------

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
FROM_EMAIL = os.environ.get("GMAIL_ADDRESS")

def send_email(to_email: str, subject: str, html: str):
    try:
        sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
        message = Mail(
            from_email=FROM_EMAIL,
            to_emails=to_email,
            subject=subject,
            html_content=html
        )
        response = sg.send(message)
        logger.info(f"Email sent to {to_email} | Status: {response.status_code}")
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")


# -----------------------------
# ADMIN AUTH
# -----------------------------

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
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
    business_name: str = "Unknown"
    owner_name: str = "Unknown"
    phone: str = "Unknown"
    interest_level: str = "cold"
    mood: str = ""
    pain_points: str = ""
    roi_reaction: str = ""
    objection: str = ""
    notes: str = ""


class CallLog(BaseModel):
    caller_phone: str = "Unknown"
    call_duration: str = ""
    call_outcome: str = ""
    summary: str = ""


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

            # Reject past dates
            try:
                apt_date = datetime.strptime(appointment.date, "%d/%m/%Y").date()
                today = datetime.now(pytz.timezone("Asia/Dubai")).date()
                if apt_date < today:
                    return {
                        "success": False,
                        "message": "Cannot book an appointment in the past. Please choose a future date."
                    }
            except ValueError:
                return {
                    "success": False,
                    "message": "Invalid date format. Please use DD/MM/YYYY."
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

        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f4f4f7;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;padding:40px 20px;">
<tr><td align="center">
<table width="580" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.10);">

  <!-- HEADER -->
  <tr><td style="background:#1a1916;padding:32px 48px;text-align:center;">
    <p style="margin:0;font-size:26px;font-weight:800;color:#ffffff;letter-spacing:-1px;">VoxDesk</p>
    <p style="margin:6px 0 0;font-size:11px;color:rgba(255,255,255,0.35);letter-spacing:3px;text-transform:uppercase;">AI Receptionist</p>
  </td></tr>

  <!-- GREEN BANNER -->
  <tr><td style="background:#d1fae5;padding:18px 48px;text-align:center;">
    <p style="margin:0;font-size:16px;font-weight:700;color:#065f46;">&#10003;&nbsp; Your Appointment is Confirmed</p>
  </td></tr>

  <!-- GREETING -->
  <tr><td style="padding:40px 48px 0;">
    <p style="margin:0 0 12px;font-size:16px;font-weight:600;color:#111827;">Hi {appointment.patient_name},</p>
    <p style="margin:0;font-size:14px;color:#6b7280;line-height:1.8;">Great news — your appointment has been successfully booked through VoxDesk. We have everything confirmed on our end. Please review the details below and save this email for your records.</p>
  </td></tr>

  <!-- DETAILS BOX -->
  <tr><td style="padding:28px 48px 0;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;">
      <tr><td style="padding:14px 22px;background:#f3f4f6;border-bottom:1px solid #e5e7eb;">
        <p style="margin:0;font-size:11px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:1.5px;">Appointment Details</p>
      </td></tr>
      <tr><td style="padding:16px 22px;border-bottom:1px solid #e5e7eb;">
        <p style="margin:0;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">Doctor</p>
        <p style="margin:5px 0 0;font-size:15px;font-weight:600;color:#111827;">Dr. {appointment.doctor_name}</p>
      </td></tr>
      <tr><td style="padding:16px 22px;border-bottom:1px solid #e5e7eb;">
        <p style="margin:0;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">Date</p>
        <p style="margin:5px 0 0;font-size:15px;font-weight:600;color:#111827;">{appointment.date}</p>
      </td></tr>
      <tr><td style="padding:16px 22px;border-bottom:1px solid #e5e7eb;">
        <p style="margin:0;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">Time</p>
        <p style="margin:5px 0 0;font-size:15px;font-weight:600;color:#111827;">{appointment.time}</p>
      </td></tr>
      <tr><td style="padding:16px 22px;">
        <p style="margin:0;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">Appointment ID</p>
        <p style="margin:5px 0 0;font-size:15px;font-weight:700;color:#111827;font-family:monospace;background:#e5e7eb;display:inline-block;padding:4px 10px;border-radius:5px;">{appointment_id}</p>
      </td></tr>
    </table>
  </td></tr>

  <!-- WHAT TO BRING -->
  <tr><td style="padding:28px 48px 0;">
    <p style="margin:0 0 14px;font-size:14px;font-weight:700;color:#111827;">&#128203;&nbsp; What to Bring</p>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td width="20" valign="top" style="padding-top:2px;"><p style="margin:0;font-size:13px;color:#059669;">&#10003;</p></td>
        <td><p style="margin:0 0 8px;font-size:13px;color:#6b7280;line-height:1.6;">A valid photo ID (passport, national ID, or driving licence)</p></td>
      </tr>
      <tr>
        <td width="20" valign="top" style="padding-top:2px;"><p style="margin:0;font-size:13px;color:#059669;">&#10003;</p></td>
        <td><p style="margin:0 0 8px;font-size:13px;color:#6b7280;line-height:1.6;">Any previous medical records or test results if applicable</p></td>
      </tr>
      <tr>
        <td width="20" valign="top" style="padding-top:2px;"><p style="margin:0;font-size:13px;color:#059669;">&#10003;</p></td>
        <td><p style="margin:0 0 8px;font-size:13px;color:#6b7280;line-height:1.6;">Please arrive 10 minutes early to complete any paperwork</p></td>
      </tr>
      <tr>
        <td width="20" valign="top" style="padding-top:2px;"><p style="margin:0;font-size:13px;color:#059669;">&#10003;</p></td>
        <td><p style="margin:0;font-size:13px;color:#6b7280;line-height:1.6;">Your insurance card if applicable</p></td>
      </tr>
    </table>
  </td></tr>

  <!-- RESCHEDULE / CANCEL -->
  <tr><td style="padding:28px 48px 0;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:20px 22px;">
      <tr><td>
        <p style="margin:0 0 6px;font-size:13px;font-weight:700;color:#92400e;">&#128336;&nbsp; Need to Cancel or Reschedule?</p>
        <p style="margin:0;font-size:13px;color:#78350f;line-height:1.7;">Simply reply to this email or call us and quote your Appointment ID: <strong style="font-family:monospace;">{appointment_id}</strong>. We kindly ask for at least 24 hours notice so we can offer your slot to another patient.</p>
      </td></tr>
    </table>
  </td></tr>

  <!-- CLOSING -->
  <tr><td style="padding:28px 48px 36px;">
    <p style="margin:0 0 16px;font-size:14px;color:#6b7280;line-height:1.8;">If you have any questions before your appointment, do not hesitate to reach out. We look forward to seeing you!</p>
    <p style="margin:0;font-size:14px;color:#374151;font-weight:600;">Warm regards,</p>
    <p style="margin:4px 0 0;font-size:14px;color:#374151;">The VoxDesk Team</p>
  </td></tr>

  <!-- DIVIDER -->
  <tr><td style="padding:0 48px;"><hr style="border:none;border-top:1px solid #e5e7eb;margin:0;"></td></tr>

  <!-- FOOTER -->
  <tr><td style="padding:24px 48px;text-align:center;">
    <p style="margin:0;font-size:12px;color:#9ca3af;">This confirmation was sent automatically by <strong>VoxDesk AI Receptionist</strong>.</p>
    <p style="margin:6px 0 0;font-size:11px;color:#d1d5db;">&#127760;&nbsp; voxdesk.com &nbsp;|&nbsp; Powered by VoxDesk &copy; 2026</p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""

        threading.Thread(
            target=send_email,
            args=(appointment.email, f"Appointment Confirmed — {appointment.date} at {appointment.time}", html)
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
                INSERT INTO leads VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                lead_id,
                lead.business_name,
                lead.owner_name,
                lead.phone,
                lead.interest_level,
                lead.mood,
                lead.pain_points,
                lead.roi_reaction,
                lead.objection,
                lead.notes,
                datetime.utcnow()
            ))

            conn.commit()
            logger.info(f"Lead saved: {lead_id} | {lead.business_name} | {lead.interest_level} | {lead.mood}")

        return {"success": True, "message": "Lead saved"}

    except Exception as e:
        logger.error(f"Error saving lead: {e}")
        return {"success": False, "message": "Something went wrong. Please try again."}


# -----------------------------
# BOOK DEMO
# -----------------------------

@app.get("/check-slot")
def check_slot(date: str, time: str):
    """Check if a time slot is already booked"""
    try:
        with get_db() as (conn, cur):
            cur.execute("""
                SELECT COUNT(*) FROM demos WHERE date = %s AND time = %s
            """, (date, time))
            count = cur.fetchone()[0]
        if count > 0:
            # Find next available slots on that day
            cur2_conn = None
            with get_db() as (conn2, cur2):
                cur2.execute("""
                    SELECT time FROM demos WHERE date = %s ORDER BY time
                """, (date,))
                booked_times = [r[0] for r in cur2.fetchall()]
            return {
                "available": False,
                "message": f"Sorry, {time} on {date} is already booked.",
                "booked_times": booked_times
            }
        return {"available": True, "message": "Slot is available"}
    except Exception as e:
        logger.error(f"Error checking slot: {e}")
        return {"available": True, "message": "Slot check failed, proceeding"}


@app.post("/book-demo")
def book_demo(demo: Demo):
    try:
        with get_db() as (conn, cur):

            # DOUBLE BOOKING PROTECTION
            cur.execute("""
                SELECT COUNT(*) FROM demos WHERE date = %s AND time = %s
            """, (demo.date, demo.time))
            already_booked = cur.fetchone()[0]

            if already_booked > 0:
                # Find other booked times on that day to suggest alternatives
                cur.execute("""
                    SELECT time FROM demos WHERE date = %s ORDER BY time
                """, (demo.date,))
                booked_times = [r[0] for r in cur.fetchall()]
                logger.warning(f"Double booking attempt: {demo.date} at {demo.time} by {demo.name}")
                return {
                    "success": False,
                    "message": f"That time slot is already taken. The following times are booked on {demo.date}: {', '.join(booked_times)}. Please choose a different time.",
                    "already_booked": True,
                    "booked_times": booked_times
                }

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

        GOOGLE_MEET_LINK = os.environ.get("GOOGLE_MEET_LINK", "https://meet.google.com/voxdesk-demo")

        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f4f4f7;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;padding:40px 20px;">
<tr><td align="center">
<table width="580" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.10);">

  <!-- HEADER -->
  <tr><td style="background:#1a1916;padding:32px 48px;text-align:center;">
    <p style="margin:0;font-size:26px;font-weight:800;color:#ffffff;letter-spacing:-1px;">VoxDesk</p>
    <p style="margin:6px 0 0;font-size:11px;color:rgba(255,255,255,0.35);letter-spacing:3px;text-transform:uppercase;">AI Receptionist</p>
  </td></tr>

  <!-- GREEN BANNER -->
  <tr><td style="background:#dcfce7;padding:18px 48px;text-align:center;">
    <p style="margin:0;font-size:16px;font-weight:700;color:#166534;">&#9989;&nbsp; Your Demo is Confirmed — You are All Set!</p>
  </td></tr>

  <!-- GREETING -->
  <tr><td style="padding:40px 48px 0;">
    <p style="margin:0 0 12px;font-size:16px;font-weight:600;color:#111827;">Hi {demo.name},</p>
    <p style="margin:0;font-size:14px;color:#6b7280;line-height:1.8;">Your VoxDesk demo is confirmed. Suhaib will walk you through the system live — you will actually hear the AI answering a real call and booking an appointment in real time. No slides, no fluff, just the product.</p>
  </td></tr>

  <!-- DETAILS BOX -->
  <tr><td style="padding:28px 48px 0;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;">
      <tr><td style="padding:14px 22px;background:#f3f4f6;border-bottom:1px solid #e5e7eb;">
        <p style="margin:0;font-size:11px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:1.5px;">Demo Details</p>
      </td></tr>
      <tr><td style="padding:16px 22px;border-bottom:1px solid #e5e7eb;">
        <p style="margin:0;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">&#128197; Date</p>
        <p style="margin:5px 0 0;font-size:15px;font-weight:600;color:#111827;">{demo.date}</p>
      </td></tr>
      <tr><td style="padding:16px 22px;border-bottom:1px solid #e5e7eb;">
        <p style="margin:0;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">&#128336; Time</p>
        <p style="margin:5px 0 0;font-size:15px;font-weight:600;color:#111827;">{demo.time}</p>
      </td></tr>
      <tr><td style="padding:16px 22px;">
        <p style="margin:0;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">&#127909; Platform</p>
        <p style="margin:5px 0 0;font-size:15px;font-weight:600;color:#111827;">Google Meet — no download needed</p>
      </td></tr>
    </table>
  </td></tr>

  <!-- GOOGLE MEET BUTTON -->
  <tr><td style="padding:32px 48px 0;text-align:center;">
    <p style="margin:0 0 16px;font-size:14px;font-weight:600;color:#111827;">Your meeting link is ready. Click below to join at the scheduled time:</p>
    <a href="{GOOGLE_MEET_LINK}" style="display:inline-block;background:#1a73e8;color:#ffffff;font-size:15px;font-weight:700;padding:16px 40px;border-radius:8px;text-decoration:none;letter-spacing:0.3px;">&#127909;&nbsp; Join Google Meet</a>
    <p style="margin:14px 0 0;font-size:12px;color:#9ca3af;">Or copy this link: <span style="color:#1a73e8;">{GOOGLE_MEET_LINK}</span></p>
  </td></tr>

  <!-- WHAT TO EXPECT -->
  <tr><td style="padding:28px 48px 0;">
    <p style="margin:0 0 14px;font-size:14px;font-weight:700;color:#111827;">&#127775;&nbsp; What We Will Cover</p>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td width="24" valign="top"><p style="margin:0;font-size:13px;color:#3b82f6;">&#8594;</p></td>
        <td><p style="margin:0 0 10px;font-size:13px;color:#6b7280;line-height:1.7;">Live demo of VoxDesk answering a real inbound call and booking an appointment automatically</p></td>
      </tr>
      <tr>
        <td width="24" valign="top"><p style="margin:0;font-size:13px;color:#3b82f6;">&#8594;</p></td>
        <td><p style="margin:0 0 10px;font-size:13px;color:#6b7280;line-height:1.7;">How the AI handles after hours calls, cancellations, and questions without any human</p></td>
      </tr>
      <tr>
        <td width="24" valign="top"><p style="margin:0;font-size:13px;color:#3b82f6;">&#8594;</p></td>
        <td><p style="margin:0 0 10px;font-size:13px;color:#6b7280;line-height:1.7;">Your client dashboard — appointments, analytics, and full control in one place</p></td>
      </tr>
      <tr>
        <td width="24" valign="top"><p style="margin:0;font-size:13px;color:#3b82f6;">&#8594;</p></td>
        <td><p style="margin:0;font-size:13px;color:#6b7280;line-height:1.7;">Pricing, setup time, and how fast your business goes live</p></td>
      </tr>
    </table>
  </td></tr>

  <!-- REMINDER BOX -->
  <tr><td style="padding:28px 48px 0;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#fefce8;border:1px solid #fde68a;border-radius:10px;padding:20px 22px;">
      <tr><td>
        <p style="margin:0 0 6px;font-size:13px;font-weight:700;color:#92400e;">&#128276;&nbsp; Quick Reminder</p>
        <p style="margin:0;font-size:13px;color:#78350f;line-height:1.7;">Add this to your calendar so you do not miss it. The Google Meet link above works directly in your browser — no app needed. If you need to reschedule just reply to this email.</p>
      </td></tr>
    </table>
  </td></tr>

  <!-- CLOSING -->
  <tr><td style="padding:28px 48px 36px;">
    <p style="margin:0 0 16px;font-size:14px;color:#6b7280;line-height:1.8;">Looking forward to showing you what VoxDesk can do for your business. See you at the demo!</p>
    <p style="margin:0;font-size:14px;color:#374151;font-weight:600;">Suhaib</p>
    <p style="margin:4px 0 0;font-size:13px;color:#9ca3af;">Founder, VoxDesk</p>
  </td></tr>

  <!-- DIVIDER -->
  <tr><td style="padding:0 48px;"><hr style="border:none;border-top:1px solid #e5e7eb;margin:0;"></td></tr>

  <!-- FOOTER -->
  <tr><td style="padding:24px 48px;text-align:center;">
    <p style="margin:0;font-size:12px;color:#9ca3af;">This confirmation was sent automatically by <strong>VoxDesk AI</strong>. Harvey booked this for you.</p>
    <p style="margin:6px 0 0;font-size:11px;color:#d1d5db;">&#127760;&nbsp; voxdesk.com &nbsp;|&nbsp; Powered by VoxDesk &copy; 2026</p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""

        threading.Thread(
            target=send_email,
            args=(demo.email, f"VoxDesk Demo Confirmed — {demo.date} at {demo.time}", html)
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
            {
                "id": r[0],
                "business_name": r[1],
                "owner_name": r[2],
                "phone": r[3],
                "interest_level": r[4],
                "mood": r[5] or "",
                "pain_points": r[6] or "",
                "roi_reaction": r[7] or "",
                "objection": r[8] or "",
                "notes": r[9] or "",
                "created_at": r[10].isoformat() if r[10] else None
            }
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

# -----------------------------
# LOG CALL (every single call)
# -----------------------------

@app.post("/log-call")
def log_call(log: CallLog):
    try:
        with get_db() as (conn, cur):
            call_id = "CL" + str(uuid.uuid4())[:6].upper()
            cur.execute("""
                INSERT INTO call_logs VALUES (%s,%s,%s,%s,%s,%s)
            """, (
                call_id,
                log.caller_phone,
                log.call_duration,
                log.call_outcome,
                log.summary,
                datetime.utcnow()
            ))
            conn.commit()
            logger.info(f"Call logged: {call_id} | {log.caller_phone} | {log.call_outcome}")
        return {"success": True, "message": "Call logged"}
    except Exception as e:
        logger.error(f"Error logging call: {e}")
        return {"success": False, "message": "Something went wrong"}


# -----------------------------
# ADMIN CALL LOGS
# -----------------------------

@app.get("/admin-calls")
def admin_calls(username: str = Depends(verify_admin)):
    try:
        with get_db() as (conn, cur):
            cur.execute("SELECT * FROM call_logs ORDER BY created_at DESC")
            rows = cur.fetchall()
        return {"calls": [
            {
                "id": r[0],
                "caller_phone": r[1],
                "call_duration": r[2],
                "call_outcome": r[3],
                "summary": r[4],
                "created_at": r[5].isoformat() if r[5] else None
            }
            for r in rows
        ]}
    except Exception as e:
        logger.error(f"Error loading call logs: {e}")
        return {"calls": []}