# Transitioning PhysioBot to a Permanent WhatsApp Business Number (Production)

This guide walks you through transitioning your bot from the Meta WhatsApp developer sandbox (temporary test numbers) to a permanent, live production number for your sister's clinic.

---

## 📋 Prerequisites

Before starting, make sure you have:
1. **A Meta Business Manager Account:** You must have (or create) a business manager account on `business.facebook.com`. Having it **verified** (by uploading business registration documents) is highly recommended; otherwise, Meta imposes low daily messaging limits.
2. **A Dedicated Phone Number:** You need a phone number to act as the clinic's bot number. 
   > ⚠️ **IMPORTANT:** This number **cannot** be active on the regular WhatsApp or WhatsApp Business mobile apps. If it is currently registered on a phone, you must go to the app settings on the phone and **Delete the Account** first.

---

## 🚶 Step-by-Step Transition

### Step 1: Register the Production Phone Number on Meta
1. Log in to the **[Meta Developer Portal](https://developers.facebook.com/)**.
2. Go to **My Apps** ➔ Select your **PhysioBot** app.
3. In the left-hand menu, go to **WhatsApp** ➔ **API Setup**.
4. Scroll to the bottom of the page and click **Add Phone Number** (under Step 5: *Add a phone number to start using the API*).
5. Fill out your clinic's business profile:
   * **WhatsApp Business Profile Display Name:** Choose your clinic name (e.g. *Balance Plus HSR Layout*). Meta will review this name.
   * **Category:** Select *Medical & Health*.
   * **Business Description:** Brief description of your services.
6. Enter the dedicated phone number, select your verification method (**SMS** or **Voice Call**), and verify it.

---

### Step 2: Generate a Permanent Access Token (Admin System User)
The sandbox token expires after 24 hours. For production, you must generate a permanent token that never expires:
1. Go to your **[Meta Business Suite settings](https://business.facebook.com/settings)**.
2. In the left menu under *Users*, click **System Users**.
3. Click **Add** to create a new System User:
   * **System User Role:** Select `Admin`.
   * **System User Name:** E.g., `physiobot-prod-admin`.
4. Once created, click **Assign Assets**:
   * Under *Apps*, select your **PhysioBot app** and enable **Full Control**.
   * Click **Save Changes**.
5. Select the system user and click **Generate New Token**:
   * Select your **PhysioBot app** in the dropdown.
   * Check the boxes for the following permissions:
     * `whatsapp_business_messaging`
     * `whatsapp_business_management`
   * Click **Generate Token**.
6. ⚠️ **Copy the token immediately** and save it somewhere secure. Meta will not display this token to you again.

---

### Step 3: Configure Webhook and Signature Validation
To prevent unauthorized requests to your server, you must enable App Secret verification:
1. Go to your **Meta Developer Portal** ➔ **My Apps** ➔ **PhysioBot** ➔ **Settings** ➔ **Basic**.
2. Copy your **App Secret** (click *Show* next to it).
3. Under **WhatsApp** ➔ **Configuration**:
   * Verify that your callback URL is set to your production deployment endpoint (e.g. `https://your-app.onrender.com/webhook`).
   * Verify the `messages` subscription webhook field is toggled **ON**.

---

### Step 4: Update Production Environment Variables
On your hosting provider dashboard (e.g. Render Dashboard ➔ Environment), update the environment variables with the production keys:

| Environment Variable | Source / Value |
| :--- | :--- |
| `WHATSAPP_TOKEN` | The **Permanent Access Token** generated in **Step 2** (starts with `EAAn...`). |
| `WHATSAPP_PHONE_NUMBER_ID` | The production Phone Number ID shown under **WhatsApp** ➔ **API Setup** (this will be a different ID from your sandbox test number). |
| `WHATSAPP_APP_SECRET` | The **App Secret** retrieved in **Step 3**. (This activates signature verification on your webhook to drop non-Meta payloads). |
| `WHATSAPP_USE_TEMPLATES` | Set to `true` if you have pre-registered and approved Meta body templates; keep `false` if you want to use reactive native buttons/lists for selection and text fallback for others. |

---

### Step 5: Update `config.yaml`
Ensure your configuration file is updated with the real clinic profile details:
1. Edit **[config.yaml](file:///Users/naman/Work/Pihu-Hobby-Project/physiobot/config.yaml)** in your repository:
   * **`clinic`**: Set your sister's real clinic name, primary contact number, and timezone (`Asia/Kolkata`).
   * **`hours`**: Update the clinic opening hours, slot durations, and closed weekdays (e.g., Sunday `[6]`).
   * **`google`**: Set the production spreadsheet and calendar ID.
2. Commit and push the `config.yaml` update to your remote repository to trigger a deployment.

---

## 🧪 Post-Launch Verification
Once deployed, perform the following validation checklist:
- [ ] Visit `https://your-app.onrender.com/healthz` to confirm the container is running and `meta_configured` is `true`.
- [ ] Scan a WhatsApp QR code or message your production phone number directly.
- [ ] Verify you receive the Welcome Greeting.
- [ ] Complete the intake flow to confirm sheets write to Google Sheets.
- [ ] Select a slot and verify the booking writes to the Sheets **Bookings** tab and schedules an event in the Google Calendar.
