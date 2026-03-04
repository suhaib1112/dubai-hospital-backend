# -------------------------------
# BOOK APPOINTMENT
# -------------------------------

@app.post("/book-appointment")
def book_appointment(appointment: Appointment):

    cur.execute("""
    SELECT * FROM appointments
    WHERE doctor_name=%s AND date=%s AND time=%s AND status='Confirmed'
    """,(
        appointment.doctor_name,
        appointment.date,
        appointment.time
    ))

    existing = cur.fetchone()

    if existing:
        return {
            "success": False,
            "message": f"Dr. {appointment.doctor_name} is already booked at that time."
        }

    appointment_id = "APT" + str(uuid.uuid4())[:6].upper()

    cur.execute("""
    INSERT INTO appointments VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """,(
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

    html = f"""
    <h2>Appointment Confirmed</h2>
    <p>Doctor: {appointment.doctor_name}</p>
    <p>Date: {appointment.date}</p>
    <p>Time: {appointment.time}</p>
    <p>Appointment ID: {appointment_id}</p>
    """

    import threading

    threading.Thread(
        target=send_email,
        args=(appointment.email,"Appointment Confirmation",html)
    ).start()

    return {
        "success": True,
        "message": f"Your appointment is confirmed. Appointment ID is {appointment_id}"
    }