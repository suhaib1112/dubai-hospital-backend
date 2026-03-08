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

  <!-- BLUE BANNER -->
  <tr><td style="background:#dbeafe;padding:18px 48px;text-align:center;">
    <p style="margin:0;font-size:16px;font-weight:700;color:#1e40af;">&#128197;&nbsp; Your Demo is Scheduled</p>
  </td></tr>

  <!-- GREETING -->
  <tr><td style="padding:40px 48px 0;">
    <p style="margin:0 0 12px;font-size:16px;font-weight:600;color:#111827;">Hi {demo.name},</p>
    <p style="margin:0;font-size:14px;color:#6b7280;line-height:1.8;">Thank you for your interest in VoxDesk. Your demo has been confirmed and we are excited to show you exactly how our AI receptionist works. This will be a live walkthrough — no slides, no fluff, just the real product in action.</p>
  </td></tr>

  <!-- DETAILS BOX -->
  <tr><td style="padding:28px 48px 0;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;">
      <tr><td style="padding:14px 22px;background:#f3f4f6;border-bottom:1px solid #e5e7eb;">
        <p style="margin:0;font-size:11px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:1.5px;">Demo Details</p>
      </td></tr>
      <tr><td style="padding:16px 22px;border-bottom:1px solid #e5e7eb;">
        <p style="margin:0;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">Date</p>
        <p style="margin:5px 0 0;font-size:15px;font-weight:600;color:#111827;">{demo.date}</p>
      </td></tr>
      <tr><td style="padding:16px 22px;">
        <p style="margin:0;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">Time</p>
        <p style="margin:5px 0 0;font-size:15px;font-weight:600;color:#111827;">{demo.time}</p>
      </td></tr>
    </table>
  </td></tr>

  <!-- WHAT TO EXPECT -->
  <tr><td style="padding:28px 48px 0;">
    <p style="margin:0 0 14px;font-size:14px;font-weight:700;color:#111827;">&#127775;&nbsp; What We Will Cover</p>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td width="24" valign="top"><p style="margin:0;font-size:13px;color:#3b82f6;">&#8594;</p></td>
        <td><p style="margin:0 0 10px;font-size:13px;color:#6b7280;line-height:1.7;">A live demo of VoxDesk answering a real inbound call and booking an appointment automatically</p></td>
      </tr>
      <tr>
        <td width="24" valign="top"><p style="margin:0;font-size:13px;color:#3b82f6;">&#8594;</p></td>
        <td><p style="margin:0 0 10px;font-size:13px;color:#6b7280;line-height:1.7;">How the AI handles cancellations, reschedules, and questions without any human involvement</p></td>
      </tr>
      <tr>
        <td width="24" valign="top"><p style="margin:0;font-size:13px;color:#3b82f6;">&#8594;</p></td>
        <td><p style="margin:0 0 10px;font-size:13px;color:#6b7280;line-height:1.7;">Your client dashboard — where you see all appointments, analytics, and manage everything</p></td>
      </tr>
      <tr>
        <td width="24" valign="top"><p style="margin:0;font-size:13px;color:#3b82f6;">&#8594;</p></td>
        <td><p style="margin:0;font-size:13px;color:#6b7280;line-height:1.7;">Pricing, setup time, and how quickly your business can go live</p></td>
      </tr>
    </table>
  </td></tr>

  <!-- PREPARE -->
  <tr><td style="padding:28px 48px 0;">
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:20px 22px;">
      <tr><td>
        <p style="margin:0 0 6px;font-size:13px;font-weight:700;color:#1e40af;">&#128161;&nbsp; Before the Demo</p>
        <p style="margin:0;font-size:13px;color:#1d4ed8;line-height:1.7;">We will send you the meeting link 30 minutes before the session. No software download is needed — the demo runs entirely in your browser. Feel free to prepare any questions you have about your business or use case.</p>
      </td></tr>
    </table>
  </td></tr>

  <!-- CLOSING -->
  <tr><td style="padding:28px 48px 36px;">
    <p style="margin:0 0 16px;font-size:14px;color:#6b7280;line-height:1.8;">If something comes up and you need to reschedule, simply reply to this email and we will find a new time that works for you. We look forward to speaking with you!</p>
    <p style="margin:0;font-size:14px;color:#374151;font-weight:600;">See you soon,</p>
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