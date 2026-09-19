# Configuring WhatsApp Business API (WABA)

This app talks to WhatsApp through **Meta's WhatsApp Cloud API**. Once the app is running, go to
**`/settings`** in the dashboard — WhatsApp/Meta, Claude AI, and AWS S3 credentials are entered
and edited directly on that page (no file editing, no restart needed; values are stored in the
database and applied immediately). A smaller set of infrastructure settings (session secret,
database URL, CORS, debug mode) still live in `.env` — see `.env.example` for the full list and
[`app/config.py`](../app/config.py) for how it's all loaded.

## 1. Create a Meta App

1. Go to [developers.facebook.com/apps](https://developers.facebook.com/apps) and create an app
   with the **Business** type.
2. From the app dashboard, add the **WhatsApp** product.
3. Under **App Settings → Basic**, copy:
   - `App ID` → **Meta App ID** on `/settings`
   - `App Secret` → **Meta App Secret** on `/settings`

## 2. Get your WhatsApp Business Account (WABA) and phone number

1. In **WhatsApp → API Setup**, either use the Meta test number to get started, or add your own
   business phone number (required before going to production).
2. Copy the values shown there into the matching fields on `/settings`:
   - `Phone number ID` → **Phone Number ID**
   - `WhatsApp Business Account ID` → **WhatsApp Business Account ID**

## 3. Generate a permanent access token

The token shown by default on the API Setup page expires after 24 hours — do **not** use it in
production.

1. Go to **Business Settings → Users → System Users** and create a system user (or use an
   existing one) with **Admin** access to the app.
2. Click **Add Assets** and grant it access to your WhatsApp app.
3. Click **Generate New Token**, select the app, and check these permissions:
   - `whatsapp_business_messaging`
   - `whatsapp_business_management`
4. Copy the generated token into **Access Token** on `/settings`. This token does not expire
   unless revoked.

## 4. Configure the webhook

1. On `/settings`, set **Webhook Verify Token** to any random string you choose. Do **not** leave
   it on the repo's placeholder value (`viviz_webhook_secret_2024`); the app refuses to start in
   production with it still set (see `check_insecure_defaults` in `app/config.py`).
2. In **WhatsApp → Configuration**, set:
   - **Callback URL**: `https://<your-domain>/webhook` (shown on the `/settings` page once
     **App URL** is set)
   - **Verify Token**: the same value you set as **Webhook Verify Token**
3. Click **Verify and Save** — Meta calls your `GET /webhook` endpoint
   ([`app/routers/webhook.py`](../app/routers/webhook.py)) to confirm the token matches.
4. Subscribe to the **`messages`** webhook field at minimum. Add
   `message_template_status_update` if you use template approval flows, and
   `account_alerts`/`phone_number_quality_update` if you want quality/status alerts.

Webhook payloads are only accepted with a valid `X-Hub-Signature-256` header, verified against
**Meta App Secret**. If that value is left blank, signature checking is **disabled** and the app
logs a warning on every webhook call — set it before going live.

## 5. What's on `/settings` vs. what's still in `.env`

Editable on `/settings` — takes effect immediately, no restart:

| Field | Purpose |
|---|---|
| Phone Number ID / WhatsApp Business Account ID / Access Token | Core WhatsApp Cloud API credentials |
| Webhook Verify Token / Meta App ID / Meta App Secret | Webhook setup and signature verification |
| App URL | Your public HTTPS domain, e.g. `https://wb.viviz.in` — used to build the webhook callback URL |
| Anthropic API Key | Only needed if you use the AI auto-reply features |
| AWS Access Key ID / Secret Access Key / Region / S3 Bucket Name | Only needed if you send/receive media (images, audio, documents) |

Still `.env`-only (baked into the app at process startup, so changing these needs a restart):

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Random 32+ char string for session signing — generate your own, don't reuse the repo default |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | Login for the dashboard — change the password from the repo default |
| `DEBUG` | Must be `false` in production |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins (defaults to `https://wb.viviz.in` in `app/config.py`) |
| `DATABASE_URL` | SQLite by default; use a Postgres URL for production if needed |
| `REDIS_URL` | Used for rate limiting; falls back to in-memory if unreachable |

`app/main.py` refuses to start with `DEBUG=false` while `SECRET_KEY`, `ADMIN_PASSWORD`, or
Webhook Verify Token are still on their placeholder values — this is enforced automatically, not
just a suggestion. Values saved on `/settings` are stored in the database and re-applied on every
startup, on top of whatever is in `.env`.

## 6. Verify everything

1. Start the app and log into the dashboard.
2. Open **Settings** (`/settings`) — every credential should show a green **set** badge with no
   amber "default value" warnings.
3. Click **Test WhatsApp Connection**. A successful response shows your verified business name,
   display phone number, and quality rating — confirming Phone Number ID and Access Token are
   both correct and live against the Graph API.
4. Send yourself a test message from the dashboard, and message the WhatsApp number from your
   phone to confirm the webhook delivers it into **Conversations**.

## 7. Before going live

- Submit the app for **App Review** if you need permissions beyond what a development app
  allows, and complete **Business Verification** in Meta Business Manager — required to message
  users outside your registered test numbers.
- Get your message templates approved under **Templates** in the dashboard before sending
  broadcasts.
- Double-check `DEBUG=false`, real `SECRET_KEY`/`ADMIN_PASSWORD` in `.env`, and that **Meta App
  Secret** is set on `/settings` so webhook signatures are verified.

## 8. Consent and broadcast compliance

Configure the customer-facing business name, published privacy-policy URL, support email or phone,
and actual WhatsApp business phone number on `/settings` before creating broadcasts. The actual phone
number is used for opt-in links; it is different from Meta's Phone Number ID.

The platform fails closed for broadcasts:

- A normal inbound support message does **not** grant marketing consent.
- Manual and CSV consent must include the exact disclosure, when consent was obtained, and evidence.
- Consent is category-specific. `CONFIRM MARKETING` grants marketing consent; `CONFIRM UPDATES`
  grants utility-message consent.
- `STOP` revokes every category. `STOP MARKETING` and `STOP UPDATES` revoke one category.
- Consent, block status, template approval, frequency limits, and Meta phone quality are checked again
  immediately before delivery, including for scheduled campaigns.
- Marketing templates must contain clear STOP/opt-out wording or an opt-out button.
- Regulated/restricted-product broadcasts are disabled; enabling them requires a separate implementation
  for country, age, licensing, and Meta permission controls.

CSV contacts may include `marketing_opt_in=yes`, but the grant is accepted only when the row also
contains `consent_evidence`, `consent_disclosure`, and an ISO-formatted `consent_at`. An optional
`consent_proof_reference` can point to the source form or CRM record. Imported contacts without this
evidence remain in the CRM but cannot receive broadcasts.

These technical controls do not replace review of campaign content, the published privacy policy,
the Meta Business profile, regulated-industry restrictions, or applicable local law. The operator must
complete the compliance declaration for each campaign.
