# PhysioBot Local Testing & API Guide

This guide describes how to run and test the PhysioBot application locally without setting up the Meta WhatsApp Cloud API.

---

## 🚀 Running the Server

Make sure your virtual environment is active, and then run the FastAPI server:

```bash
./.venv/bin/uvicorn physiobot.app:app --reload
```

* **API Docs URL:** [http://localhost:8000/docs](http://localhost:8000/docs) (Interactive Swagger UI)
* **Health Check URL:** [http://localhost:8000/healthz](http://localhost:8000/healthz)

---

## 💬 Simulating a Conversation

You can simulate WhatsApp chat messages locally by sending HTTP POST requests to the `/simulate` endpoint.

### Step 1: Initialize Conversation (Greeting & Intent)
Send an opening message indicating the complaint and desire to book.

**cURL Command:**
```bash
curl -s localhost:8000/simulate -H 'content-type: application/json' \
  -d '{"text":"Hi, I have knee pain and want to book a visit"}'
```

**Response:**
```json
{
  "reply": "Hello! I'm glad you're taking steps to address your knee pain. Could you please share your full name and phone number so we can proceed?"
}
```

---

### Step 2: Provide Patient Details (Name & Phone)
Send your name and contact number. The agent will process this and write your details to the Google Sheet.

**cURL Command:**
```bash
curl -s localhost:8000/simulate -H 'content-type: application/json' \
  -d '{"text":"My name is Naman and my phone is +91-7054256969"}'
```

**Response:**
```json
{
  "reply": "Great! Here are the available times for you tomorrow:\n\n- 10:00\n- 10:45\n- 11:30\n- 12:15\n- 13:00\n- 13:45\n- 14:30\n- 15:15\n- 16:00\n- 16:45\n- 17:30\n- 18:15\n\nWhich time works best for you?"
}
```

* **Behind the Scenes:** The agent executed the `save_patient_info` tool and successfully created/updated a row in the **Patients** tab of your Google Sheet.

---

### Step 3: Request / Confirm Available Times
If not already listed, request appointment slots for a specific day.

**cURL Command:**
```bash
curl -s localhost:8000/simulate -H 'content-type: application/json' \
  -d '{"text":"I want to book an appointment for tomorrow"}'
```

**Response:**
```json
{
  "reply": "Perfect! The available times for tomorrow are:\n\n- 10:00\n- 10:45\n- 11:30\n- 12:15\n- 13:00\n- 13:45\n- 14:30\n- 15:15\n- 16:00\n- 16:45\n- 17:30\n- 18:15\n\nWhich time suits you best?"
}
```

* **Behind the Scenes:** The agent executed the `get_free_slots` tool to retrieve existing busy times from Google Calendar, subtracted them from working hours, and returned only available times.

---

### Step 4: Finalize Booking
Confirm the exact time slot you wish to book.

**cURL Command:**
```bash
curl -s localhost:8000/simulate \
  -H "content-type: application/json" \
  -d "{\"text\":\"Let's book the 11:30 AM slot\"}"
```

**Response:**
```json
{
  "reply": "Your appointment is booked for tomorrow at 11:30 AM. Looking forward to seeing you then! If you have any further questions or need assistance, feel free to ask."
}
```

* **Behind the Scenes:** The agent executed the `create_booking` tool. It added a new event to your Google Calendar and appended a row with details (including the generated Calendar `EventId`) in the **Bookings** tab of your Google Sheet.
