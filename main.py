from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uuid
from datetime import datetime
import pytz
import requests

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# -------------------------------
# In-Memory Database
# -------------------------------

appointments_db = []

# 24-hour schedule
doctor_schedule = {
    "ahmed": ["09:00", "10:00", "11:00"],
    "sara": ["13:00", "14:00", "15:00"]
}

# -------------------------------
# Normalization Helpers
# -------------------------------

def normalize_doctor(name: str):
    if not name:
        return ""

    name = name.lower().strip()

    for prefix in ["dr.", "dr ", "doctor "]:
        if name.startswith(prefix):
            name = name.replace(prefix, "")

    for existing in doctor_schedule.keys():
        if existing in name:
            return existing

    return name


def normalize_time(time_str: str):
    if not time_str:
        return ""

    time_str = time_str.strip().upper()

    try:
        converted = datetime.strptime(time_str, "%I %p")
        return converted.strftime("%H:00")
    except:
        pass

    try:
        converted = datetime.strptime(time_str, "%I:%M %p")
        return converted.strftime("%H:%M")
    except:
        pass

    try:
        datetime.strptime(time_str, "%H:%M")
        return time_str
    except:
        pass

    if time_str.isdigit():
        return time_str.zfill(2) + ":00"

    return time_str


# -------------------------------
# Models
# -------------------------------

class Appointment(BaseModel):
    patient_name: str
    doctor_name: str
    date: str
    time: str


class AvailabilityRequest(BaseModel):
    department: str
    doctor_name: str
    preferred_date: str


class CancelRequest(BaseModel):
    appointment_id: str


# -------------------------------
# Routes
# -------------------------------

@app.get("/")
def root():
    return {
        "success": True,
        "message": "Dubai Hospital Backend is running"
    }


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


@app.post("/check-doctor-availability")
def check_doctor_availability(request: AvailabilityRequest):

    doctor = normalize_doctor(request.doctor_name)
    date = request.preferred_date.strip()

    if doctor not in doctor_schedule:
        return {"success": False, "message": "Doctor not found", "data": None}

    booked = [
        appt["time"]
        for appt in appointments_db
        if appt["doctor_name"].lower() == doctor and appt["date"] == date
    ]

    available = [
        slot for slot in doctor_schedule[doctor]
        if slot not in booked
    ]

    return {
        "success": True,
        "message": f"Available slots for Dr. {doctor.title()} on {date}",
        "data": {
            "doctor": doctor.title(),
            "date": date,
            "available_slots": available
        }
    }


@app.post("/book-appointment")
def book_appointment(appointment: Appointment):

    doctor = normalize_doctor(appointment.doctor_name)
    time = normalize_time(appointment.time)
    date = appointment.date.strip()

    if doctor not in doctor_schedule:
        return {"success": False, "message": "Doctor not found", "data": None}

    if time not in doctor_schedule[doctor]:
        return {"success": False, "message": "Invalid time slot", "data": None}

    for appt in appointments_db:
        if (
            appt["doctor_name"].lower() == doctor and
            appt["date"] == date and
            appt["time"] == time
        ):
            return {
                "success": False,
                "message": "That time slot is already booked.",
                "data": None
            }

    appointment_id = "APT-" + str(uuid.uuid4())[:8].upper()

    new_appt = {
        "appointment_id": appointment_id,
        "patient_name": appointment.patient_name.strip(),
        "doctor_name": doctor.title(),
        "date": date,
        "time": time
    }

    appointments_db.append(new_appt)

    # Send booking data to Make webhook
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
        "message": f"Your appointment with Dr. {doctor.title()} on {date} at {time} is confirmed. Your confirmation ID is {appointment_id}.",
        "data": new_appt
    }


@app.post("/cancel-appointment")
def cancel_appointment(request: CancelRequest):

    appointment_id = request.appointment_id.strip().upper()

    for appt in appointments_db:
        if appt["appointment_id"].upper() == appointment_id:
            appointments_db.remove(appt)
            return {
                "success": True,
                "message": f"Appointment {appointment_id} has been successfully cancelled.",
                "data": appt
            }

    return {"success": False, "message": "Appointment ID not found", "data": None}


# -------------------------------
# Admin Dashboard
# -------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "appointments": appointments_db
        }
    )