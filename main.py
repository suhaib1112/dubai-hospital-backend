from fastapi import FastAPI
from pydantic import BaseModel
import uuid

app = FastAPI()

# -------------------------------
# Fake In-Memory Database
# -------------------------------

appointments_db = []

doctor_schedule = {
    "Ahmed": ["09:00 AM", "10:00 AM", "11:00 AM"],
    "Sara": ["01:00 PM", "02:00 PM", "03:00 PM"]
}

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

    doctor = request.doctor_name
    date = request.preferred_date

    if doctor not in doctor_schedule:
        return {
            "success": False,
            "message": f"Dr. {doctor} not found",
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
        "message": f"Available slots for Dr. {doctor} on {date}",
        "data": {
            "doctor": doctor,
            "date": date,
            "available_slots": available_slots
        }
    }


@app.post("/book-appointment")
def book_appointment(appointment: Appointment):

    if appointment.doctor_name not in doctor_schedule:
        return {
            "success": False,
            "message": "Doctor not found",
            "data": None
        }

    if appointment.time not in doctor_schedule[appointment.doctor_name]:
        return {
            "success": False,
            "message": "Invalid time slot",
            "data": None
        }

    for appt in appointments_db:
        if (
            appt["doctor_name"] == appointment.doctor_name
            and appt["date"] == appointment.date
            and appt["time"] == appointment.time
        ):
            return {
                "success": False,
                "message": "That time slot is already booked. Please choose another time.",
                "data": None
            }

    # Generate clean uppercase appointment ID
    appointment_id = "APT-" + str(uuid.uuid4())[:8].upper()

    new_appointment = {
        "appointment_id": appointment_id,
        "patient_name": appointment.patient_name,
        "doctor_name": appointment.doctor_name,
        "date": appointment.date,
        "time": appointment.time
    }

    appointments_db.append(new_appointment)

    # 👇 Voice-ready natural message
    return {
        "success": True,
        "message": (
            f"Great news {appointment.patient_name}! "
            f"Your appointment with Dr. {appointment.doctor_name} "
            f"is confirmed for {appointment.date} at {appointment.time}. "
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
                "message": (
                    f"Your appointment with ID {request.appointment_id} "
                    f"has been successfully cancelled."
                ),
                "data": appt
            }

    return {
        "success": False,
        "message": "Appointment ID not found",
        "data": None
    }