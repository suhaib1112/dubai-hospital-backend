from fastapi import FastAPI
from pydantic import BaseModel
import uuid

app = FastAPI()

# -------------------------------
# In-Memory Database
# -------------------------------

appointments_db = []

doctor_schedule = {
    "ahmed": ["09:00 AM", "10:00 AM", "11:00 AM"],
    "sara": ["01:00 PM", "02:00 PM", "03:00 PM"]
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
    return name.strip()


def normalize_time(time_str: str):
    try:
        if not time_str:
            return ""

        time_str = time_str.strip().upper()

        # Handle "10AM"
        time_str = time_str.replace("AM", " AM").replace("PM", " PM")

        parts = time_str.split()

        # Case 1: Only hour provided ("10")
        if len(parts) == 1:
            hour = parts[0]
            if hour.isdigit():
                hour = hour.zfill(2)
                return f"{hour}:00 AM"
            return time_str

        # Case 2: Hour + period
        if len(parts) >= 2:
            hour_part = parts[0]
            period = parts[1]

            if ":" not in hour_part:
                if hour_part.isdigit():
                    hour_part = hour_part.zfill(2)
                    hour_part = f"{hour_part}:00"

            return f"{hour_part} {period}"

        return time_str

    except Exception:
        # Never crash backend
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


@app.post("/check-doctor-availability")
def check_doctor_availability(request: AvailabilityRequest):

    doctor = normalize_doctor(request.doctor_name)
    date = request.preferred_date

    if doctor not in doctor_schedule:
        return {
            "success": False,
            "message": "Doctor not found",
            "data": None
        }

    booked_times = [
        appt["time"]
        for appt in appointments_db
        if appt["doctor_name"] == doctor and appt["date"] == date
    ]

    available_slots = [
        slot for slot in doctor_schedule[doctor]
        if slot not in booked_times
    ]

    return {
        "success": True,
        "message": f"Available slots for Dr. {doctor.title()} on {date}",
        "data": {
            "doctor": doctor.title(),
            "date": date,
            "available_slots": available_slots
        }
    }


@app.post("/book-appointment")
def book_appointment(appointment: Appointment):

    doctor = normalize_doctor(appointment.doctor_name)
    time = normalize_time(appointment.time)
    date = appointment.date.strip()

    if doctor not in doctor_schedule:
        return {
            "success": False,
            "message": "Doctor not found",
            "data": None
        }

    if time not in doctor_schedule[doctor]:
        return {
            "success": False,
            "message": "Invalid time slot",
            "data": None
        }

    for appt in appointments_db:
        if (
            appt["doctor_name"] == doctor
            and appt["date"] == date
            and appt["time"] == time
        ):
            return {
                "success": False,
                "message": "That time slot is already booked. Please choose another time.",
                "data": None
            }

    appointment_id = "APT-" + str(uuid.uuid4())[:8].upper()

    new_appointment = {
        "appointment_id": appointment_id,
        "patient_name": appointment.patient_name.strip(),
        "doctor_name": doctor,
        "date": date,
        "time": time
    }

    appointments_db.append(new_appointment)

    return {
        "success": True,
        "message": (
            f"Great news {appointment.patient_name}! "
            f"Your appointment with Dr. {doctor.title()} "
            f"is confirmed for {date} at {time}. "
            f"Your confirmation ID is {appointment_id}. "
            f"Please keep this ID for future reference."
        ),
        "data": new_appointment
    }


@app.post("/cancel-appointment")
def cancel_appointment(request: CancelRequest):

    for appt in appointments_db:
        if appt["appointment_id"] == request.appointment_id:
            appointments_db.remove(appt)
            return {
                "success": True,
                "message": f"Your appointment with ID {request.appointment_id} has been successfully cancelled.",
                "data": appt
            }

    return {
        "success": False,
        "message": "Appointment ID not found",
        "data": None
    }