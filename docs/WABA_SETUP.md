# Meta WhatsApp Business Cloud API setup guide

This guide configures the live Viviz WhatsApp dashboard to use Meta's official WhatsApp Business
Platform Cloud API.

## Production URLs

| Purpose | URL |
|---|---|
| Dashboard | `https://meta.viviz.in/` |
| Login | `https://meta.viviz.in/login` |
| Application settings | `https://meta.viviz.in/settings` |
| Webhook callback | `https://meta.viviz.in/webhook` |
| API health check | `https://meta.viviz.in/api/v1/health` |
| Webhook logs | `https://meta.viviz.in/webhook/logs` |

The webhook verification token is a secret value chosen by you. It is not the Meta App Secret and
not the WhatsApp access token.

## What you will create

By the end of this process you should have:

- A verified Meta business portfolio owned by the business.
- A Meta developer app with the WhatsApp product.
- A WhatsApp Business Account (WABA).
- A production phone number registered with Cloud API.
- A production system-user access token.
- A verified and subscribed webhook.
- An active payment method.
- Approved message templates.
- Recorded opt-in evidence for every broadcast recipient.

This guide assumes the business is connecting its own WABA. If this software will onboard or
manage WABAs belonging to other companies, use Meta's Tech Provider/Embedded Signup process. That
requires additional permissions, App Review, access verification, and product work not covered by
the normal direct-business setup.

## Values that are commonly confused

| Value | What it identifies | Where to find it |
|---|---|---|
| Meta App ID | The developer application | Meta App Dashboard, **App settings > Basic** |
| Meta App Secret | Signs and verifies app/webhook traffic | Meta App Dashboard, **App settings > Basic** |
| WABA ID | The WhatsApp Business Account | **WhatsApp > API Setup** or WhatsApp Manager |
| Phone Number ID | Meta's API ID for the registered number | **WhatsApp > API Setup** |
| Display phone number | The real customer-facing number | WhatsApp Manager |
| Access token | Authorizes Graph API requests | Temporary token in API Setup; production token from a system user |
| Webhook verify token | A random secret that you create | Enter the same value in this app and Meta's webhook form |

Never paste an access token, App Secret, admin password, or database URL into source control,
screenshots, support tickets, or chat messages.

## 1. Prepare the business before creating the app

Have the following ready:

- A personal Facebook account protected with two-factor authentication.
- Admin access to the correct Meta business portfolio.
- The legal business name, address, website, and registration documents.
- A business-domain email address.
- A public privacy policy describing WhatsApp messaging and data handling.
- Public user-data deletion instructions or a suitable deletion-request page.
- A support email address or phone number monitored by a person.
- A phone number that can receive an SMS or voice verification call.
- A credit/debit card or another Meta-supported billing method.

The legal name and address entered in Meta should exactly match the supporting documents. Avoid
creating multiple business portfolios or WABAs while troubleshooting; ownership mistakes are much
harder to correct later.

Before starting Meta configuration, confirm these deployment prerequisites:

- `https://meta.viviz.in/api/v1/health` returns HTTP 200.
- `https://meta.viviz.in/login` loads over valid HTTPS and an administrator can sign in.
- The deployment uses `DEBUG=false`, unique production secrets, PostgreSQL, and a working backup.
- The business has selected the actual public URLs it will use for its privacy policy and user-data
  deletion instructions. Record them before App Review:
  - Privacy Policy URL: `________________________________`
  - User Data Deletion URL: `________________________________`

## 2. Create or select the Meta business portfolio

1. Open [Meta Business Suite](https://business.facebook.com/) and select the intended business.
2. Open **Business settings** and confirm that the business portfolio owns the website/domain and
   that at least two trusted administrators are present.
3. In **Security Center**, require two-factor authentication for administrators.
4. Start **Business verification** if it is available or requested.
5. Supply the legal documents and complete domain/email verification requested by Meta.

Business verification and display-name review are separate processes. Completing one does not
automatically approve the other.

## 3. Create the Meta developer app

1. Open [Meta for Developers](https://developers.facebook.com/apps/).
2. Choose **Create App**.
3. Select the WhatsApp/business messaging use case when offered. In older versions of the Meta UI,
   choose an app of type **Business**.
4. Connect the app to the correct business portfolio.
5. Give the app an internal name, for example `Viviz WhatsApp Production`.
6. From the app dashboard, add the **WhatsApp** product.
7. Open **App settings > Basic** and record the **App ID** and **App Secret**.

Do not switch the app to Live mode until the privacy, deletion, contact, webhook, and production
phone settings below are complete.

## 4. Test with Meta's test number first

Meta normally creates a test WABA and test number in **WhatsApp > API Setup**.

1. Add your personal phone as a permitted test recipient.
2. Use the temporary access token and Meta's sample request to send the sample template.
3. Confirm that the message arrives before registering the production number.

Temporary tokens are suitable only for this initial check. They expire and must not be placed in the
production dashboard.

## 5. Create or select the production WABA

1. In **WhatsApp > API Setup**, select or create the production WhatsApp Business Account.
2. Confirm that the WABA belongs to the correct business portfolio.
3. Record the **WhatsApp Business Account ID**.
4. In WhatsApp Manager, complete the business profile:
   - Business display name
   - Business category and description
   - Website
   - Support email or phone
   - Address when applicable
5. Submit the display name for review if Meta requests it.

The display name must accurately represent the verified business and should be visible on the
business website. Avoid taglines, promotional wording, unnecessary punctuation, or another
company's trademark.

## 6. Add and verify the production phone number

1. Select **Add phone number** in WhatsApp Manager or API Setup.
2. Enter the exact customer-facing number with its country code.
3. Choose SMS or voice verification and enter the verification code.
4. Configure the six-digit two-step-verification PIN if prompted. Store it in the business password
   manager.
5. Record the resulting **Phone Number ID**. Do not confuse it with the real phone number.
6. Confirm that the number status is connected and that the display name is approved.

If the number is currently used by WhatsApp Messenger or the WhatsApp Business app, do not delete
or migrate it without a backup and migration plan. Use Meta's coexistence flow only if it is offered
for that account and country; otherwise use a dedicated number.

## 7. Add a payment method

1. Open WhatsApp Manager and locate the WABA's **Payment settings** or **Billing & payments**.
2. Add a supported payment method.
3. Confirm the legal billing details, currency, tax information, and spending controls.
4. Check that the WABA has no overdue balance or payment restriction.

Cloud API hosting by Meta does not make broadcasts free. Meta charges based on delivered messages,
recipient market, and message category. Marketing broadcasts are paid. Pricing and free-entry rules
change over time, so check the [official pricing page](https://whatsappbusiness.com/products/platform-pricing/)
before every large campaign.

## 8. Create a production access token

Use a system-user token instead of the temporary token shown on API Setup.

1. Open **Business settings > Users > System users**.
2. Create an Admin system user dedicated to this integration, for example `viviz-wb-production`.
3. Assign the Meta app to the system user with the access Meta requires.
4. Assign the production WhatsApp Account/WABA asset to the system user with permission to manage
   messages and templates.
5. Choose **Generate new token**, select the Meta app, and select at least:
   - `whatsapp_business_messaging`
   - `whatsapp_business_management`
6. Select the longest expiration Meta permits for this account. Some business system-user flows
   offer a non-expiring token; do not assume that every token is permanent.
7. Copy the token once and store a recovery copy in the business password manager.

Add `business_management` only if Meta specifically requires it for the asset-management operation
you are performing. Keep the token's privileges minimal.

Meta changes the names of asset tasks in Business Settings. For an owner-operated WABA, select the
task equivalent to **Full control/Manage WhatsApp account** for the WhatsApp Account asset and
**Manage app** for the app. After generating the token, the dashboard connection test is the final
proof that the selected tasks are sufficient; do not grant unrelated Pages, ad accounts, catalogs,
or financial assets.

Tokens can stop working when they expire, are revoked, lose asset access, or when an administrator,
app, WABA, or business relationship changes. Plan a rotation procedure and test a replacement token
before revoking the old token.

## 9. Complete the Meta app's production details

In **App settings > Basic**, complete the fields Meta presents, including:

- App domains: `meta.viviz.in`
- Privacy Policy URL: a public HTTPS page owned by the business
- User Data Deletion URL or deletion instructions: a public HTTPS page
- Contact email: a monitored business address
- App category and icon where required
- Terms of Service URL, if the business has one

The dashboard's privacy-policy setting is displayed to customers during opt-in; it does not publish
a privacy policy for you. The policy page must already exist on a public website.

Switch the app to **Live** after the production assets and webhook work. Complete App Review or
request Advanced Access wherever Meta's **App Review > Permissions and Features** page says it is
required. An app that manages third-party businesses requires a substantially broader review than
an app used only with the owner's WABA.

For an owner-operated app, proceed only when the permissions screen shows that the app can use the
two WhatsApp permissions with the production business asset and Meta does not show an unresolved
review or access-verification requirement. A rejected, canceled, or expired business-verification
request is not an acceptable substitute for a verified/eligible business.

## 10. Configure the Viviz dashboard

1. Sign in at `https://meta.viviz.in/login`.
2. Open `https://meta.viviz.in/settings`.
3. Enter the following values under **Meta WhatsApp Business API**:

| Dashboard field | Value from Meta |
|---|---|
| Phone Number ID | Production Phone Number ID |
| WhatsApp Business Account ID | Production WABA ID |
| Access Token | Production system-user token |
| Webhook Verify Token | A new random secret chosen by you |
| Meta App ID | App ID from App settings > Basic |
| Meta App Secret | App Secret from App settings > Basic |

4. Under **Application & Security**, enter:

| Dashboard field | Required value |
|---|---|
| App URL | `https://meta.viviz.in` |
| Customer-facing Business Name | The exact name customers recognize |
| Privacy Policy URL | The published HTTPS privacy-policy page |
| Support Email | A monitored support address |
| Support Phone | A monitored support number, preferably in international format |
| WhatsApp Business Phone | The real WhatsApp number with country code and digits only, for example `919876543210` |

5. Save the page.
6. Click **Test WhatsApp Connection**.

A successful test returns the verified name, display number, quality rating, and code-verification
status. If it fails, do not continue to broadcasts; correct the ID, token, and asset permissions.

The fields above are stored in the production database and take effect without a restart. Runtime
infrastructure fields such as `SECRET_KEY`, `ADMIN_PASSWORD`, `DEBUG`, `ALLOWED_ORIGINS`,
`DATABASE_URL`, `REDIS_URL`, and `WHATSAPP_API_VERSION` are deployment environment variables and
require a restart/redeployment when changed.

## 11. Configure and subscribe the webhook

1. In the Meta App Dashboard, open **WhatsApp > Configuration**.
2. In the Webhook section, choose **Edit** or **Configure**.
3. Enter:
   - Callback URL: `https://meta.viviz.in/webhook`
   - Verify token: exactly the same random value saved in the Viviz dashboard
4. Choose **Verify and save**.
5. Subscribe the production WABA to the app if Meta shows a separate subscription action.
6. Subscribe to the `messages` webhook field.

The `messages` field carries incoming messages and outgoing sent/delivered/read/failed status
updates used by this application. Subscribe to `marketing_messages` only if you intentionally use
the dashboard's Marketing Messages Lite onboarding. Other Meta fields are not required by the
current application.

Webhook security has two separate checks:

- Meta verifies `GET /webhook` using your Webhook Verify Token.
- The app verifies every webhook POST's `X-Hub-Signature-256` using the Meta App Secret.

If the App Secret is blank or wrong, webhook signature validation cannot be trusted. Never solve a
signature error by permanently disabling validation.

To verify the WABA subscription independently, use Meta's Graph API Explorer or another secure API
client with the production system-user token:

```text
GET /<WABA_ID>/subscribed_apps
```

The response must list the production Meta App ID. If it does not, subscribe it with:

```text
POST /<WABA_ID>/subscribed_apps
```

Use the current WhatsApp-supported Graph API version and an Authorization Bearer header. Do not put
the token in the URL, documentation, terminal history, or screenshots.

## 12. Perform the inbound-message test

1. Send a normal WhatsApp message from a personal phone to the production business number.
2. Open **Conversations** in the dashboard.
3. Confirm the contact and incoming message appear.
4. Reply from the dashboard within 24 hours.
5. Confirm the reply arrives and its status progresses to delivered/read where available.
6. Open **Webhook Logs** if the message does not appear.

An inbound support message opens the 24-hour customer-service window. It does not grant marketing
consent.

This test proves inbound delivery and service-window replies only. The controlled broadcast test in
section 15 separately proves business-initiated template delivery. Retain the test phone, timestamps,
message/campaign ID, and corresponding webhook or campaign result as launch evidence.

## 13. Set up opt-in and opt-out

Meta requires the recipient's number and opt-in permission before business-initiated messaging.
The disclosure must identify the business and explain the kinds of messages the person will receive.

Supported chat flows in this application:

| Customer message | Result |
|---|---|
| `START MARKETING` | Shows the marketing disclosure and requests confirmation |
| `CONFIRM MARKETING` | Records marketing consent after the disclosure |
| `START UPDATES` | Shows the utility/update disclosure and requests confirmation |
| `CONFIRM UPDATES` | Records utility consent after the disclosure |
| `STOP MARKETING` | Revokes marketing consent |
| `STOP UPDATES` | Revokes utility consent |
| `STOP` | Revokes all categories and blocks automated replies |

You can also open the public opt-in page from the dashboard. It creates a WhatsApp deep link using
the configured real business phone number.

For consent collected on a website, paper form, checkout, CRM, or CSV import, retain:

- The exact disclosure shown to the person.
- The message category they accepted.
- The date and time of consent.
- The collection source and supporting evidence/reference.
- The privacy-policy version or URL.

Do not pre-check consent boxes. Do not treat a purchased list, customer account, phone number, or
past transaction as WhatsApp marketing consent.

For CSV import, set `marketing_opt_in=yes` only when the same row also supplies:

- `consent_evidence`
- `consent_disclosure`
- `consent_at` as an ISO-formatted timestamp
- `consent_proof_reference` when a form, CRM record, or document reference exists

Rows without the required evidence are imported as contacts but remain ineligible for marketing
broadcasts. Manual contact editing provides equivalent disclosure, evidence, and consent-time fields.

## 14. Create and approve message templates

Business-initiated messages and messages outside the 24-hour service window must use an approved
template.

1. Open **Templates** in the dashboard.
2. Create a lowercase template name using letters, numbers, and underscores.
3. Select the correct category:
   - **MARKETING** for offers, promotions, announcements, and re-engagement.
   - **UTILITY** for a specific transaction, account, order, or requested update.
   - **AUTHENTICATION** for one-time-password/authentication use cases.
4. Select the exact language and locale that will be sent.
5. For marketing, include an unambiguous opt-out instruction such as
   `Reply STOP MARKETING to opt out.`
6. Submit the template to Meta.
7. Wait for status `APPROVED` and open the Templates page to synchronize status.

This dashboard permits broadcasts only with approved, active MARKETING or UTILITY templates.
AUTHENTICATION templates cannot be used for broadcasts. Meta may recategorize, pause, disable, or
reject a template after review.

Start with a simple static template when validating the integration. Templates containing variables
or media may require sample values/assets during Meta review and corresponding component parameters
at send time.

## 15. Run a controlled broadcast test

1. Use one or two internal phone numbers.
2. Complete the proper opt-in flow for each test recipient.
3. Confirm the contact is not blocked and has category-specific active consent.
4. Confirm the approved template appears in the broadcast form.
5. Preview the audience.
6. Review the final content, links, category, language, cost, and opt-out text.
7. Complete the compliance declaration and send or schedule the campaign.
8. Confirm sent, delivered, read, failed, and suppressed counts.
9. From one test phone, send `STOP MARKETING`.
10. Confirm the consent history records the revocation and that previewing another marketing
    campaign suppresses that number.
11. If utility consent is being used, repeat with `STOP UPDATES`; finish with `STOP` and confirm all
    categories are revoked.

At creation time and immediately before delivery, this application checks:

- Template approval, activity, category, and language.
- Category-specific consent.
- Block and opt-out status.
- Marketing frequency limits.
- Required privacy and support configuration.
- Marketing opt-out wording.
- Meta phone-number quality status.

Recipients who become ineligible are suppressed rather than sent. A red Meta quality rating blocks
the campaign. A yellow rating reduces send speed. Regulated/restricted-product broadcasts are
disabled in this application.

## 16. Understand the 24-hour window and billing

- Free-form text/media replies are allowed only during the 24 hours after the user's most recent
  message.
- Outside that window, use an approved template.
- Marketing messages are chargeable when delivered.
- Other category charges and free-entry windows depend on Meta's current pricing rules and recipient
  market.
- A Meta charge is separate from hosting, AI, storage, or any solution-provider fee.

Always consult Meta's live rate card. Do not estimate a large campaign from an old screenshot or
blog post.

## 17. Production launch checklist

- [ ] Correct business portfolio and WABA ownership confirmed.
- [ ] Business verification shows Verified/eligible, with no rejected, expired, or unresolved request.
- [ ] App is in Live mode.
- [ ] Production display name is approved.
- [ ] Production phone is connected and verified.
- [ ] Payment method is active.
- [ ] System-user token works and its rotation owner is documented.
- [ ] App Secret and webhook verify token are configured.
- [ ] `https://meta.viviz.in/webhook` is verified.
- [ ] `messages` webhook subscription is active for the production WABA.
- [ ] Inbound, reply, delivery-status, and opt-out tests pass.
- [ ] Privacy policy and deletion instructions are public.
- [ ] Business profile contains accurate support contact information.
- [ ] Approved templates use the correct category and language.
- [ ] Marketing opt-in evidence exists for every marketing recipient.
- [ ] `DEBUG=false` and production secrets are not defaults.
- [ ] Database backups and token-rotation procedures are documented.
- [ ] A small internal broadcast succeeds before importing a large audience.
- [ ] `STOP MARKETING` revocation is recorded and suppresses the test recipient.
- [ ] Phone/account quality has no red rating, policy restriction, payment hold, or messaging block.
- [ ] Test evidence records the phone, timestamps, message/campaign ID, and final delivery result.

## 18. Troubleshooting

### Webhook verification returns 403

- Confirm the callback is exactly `https://meta.viviz.in/webhook`.
- Re-enter the same verify token in Meta and the dashboard.
- Check for accidental spaces or use of the App Secret in the verify-token field.
- Confirm the production domain has a valid HTTPS certificate.

### Webhook POST returns 403 or messages do not appear

- Confirm the Meta App Secret belongs to the same Meta app sending the webhook.
- Confirm the production WABA is subscribed to the app and `messages` is enabled.
- Inspect `https://meta.viviz.in/webhook/logs` while signed in.
- Send a new inbound message; Meta's webhook test payload is not identical to every live payload.

### Test WhatsApp Connection fails

- Confirm the Phone Number ID is an ID, not the display number.
- Confirm the token belongs to the app/system user with access to this WABA.
- Reassign the app and WhatsApp Account assets to the system user if needed.
- Generate a replacement token with both WhatsApp permissions.
- Check whether the token expired or was invalidated by an admin/security change.

### Template cannot be used

- The template must be approved, active, and synchronized into the dashboard.
- The language must exactly match Meta's approved language code.
- Broadcasts accept only MARKETING and UTILITY templates.
- Marketing templates require opt-out wording.

### Free-form message is blocked

The last customer message is more than 24 hours old, the contact is blocked, or there is no known
conversation. Send an approved template to an eligible, opted-in recipient instead.

### Broadcast has zero or fewer recipients than expected

Review suppressed contacts for missing category consent, opt-out/block status, frequency caps, or
missing evidence. Importing a phone number does not grant consent.

### Graph API reports an unsupported version

`WHATSAPP_API_VERSION` is a deployment environment variable. Set it to a WhatsApp-supported Graph
API version listed in Meta's current developer documentation, redeploy, and rerun the connection
test. Do not change versions blindly in the dashboard because this value is loaded at application
startup.

### Meta restricts or disables messaging

Stop broadcasts, inspect Account Quality and WhatsApp Manager, resolve payment or policy alerts,
and follow Meta's appeal path when appropriate. Do not retry around a restriction or switch to an
unofficial bulk-sending tool.

## 19. Security and operating routine

Daily or before a campaign:

- Check phone quality, account alerts, template status, and payment status.
- Review failed/suppressed recipients and customer opt-outs.
- Send only expected, timely, relevant messages.

Monthly:

- Review system users, admins, WABA assets, and access-token ownership.
- Test backup restoration and data-erasure handling.
- Review privacy/support details and consent evidence.
- Review Meta's policy, pricing, and developer changelog for changes.

Immediately rotate credentials when a token or App Secret appears in source control, screenshots,
logs, tickets, or chat. Update the dashboard with the replacement, test it, and then revoke the old
credential.

## Official references

- [WhatsApp Business Messaging Policy](https://whatsappbusiness.com/policy/)
- [WhatsApp Business Platform pricing](https://whatsappbusiness.com/products/platform-pricing/)
- [WhatsApp Business Platform developer hub](https://whatsappbusiness.com/developers/developer-hub/)
- [WhatsApp Business Platform features](https://whatsappbusiness.com/products/business-platform-features/)
- [Meta developer apps](https://developers.facebook.com/apps/)
- [Meta Business Suite](https://business.facebook.com/)
- [Meta WhatsApp Business Platform Postman collection](https://www.postman.com/meta/whatsapp-business-platform/overview)

Meta changes dashboard labels, eligibility, versions, pricing, and review requirements over time.
When this guide and the current Meta dashboard differ, follow Meta's current product instructions
and update this document.
