from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.broadcast import Broadcast, BroadcastRecipient
from app.models.consent import ConsentEvent
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.template import MessageTemplate
from app.services.audit import log_event

CONSENT_CATEGORIES = {"marketing", "utility", "authentication"}


def normalize_category(category: str) -> str:
    value = (category or "").strip().lower()
    if value not in CONSENT_CATEGORIES:
        raise ValueError(f"Unsupported consent category: {category}")
    return value


def default_disclosure(category: str) -> str:
    category = normalize_category(category)
    purpose = {
        "marketing": "marketing offers, product news, and recommendations",
        "utility": "order, appointment, payment, and account updates",
        "authentication": "one-time passwords and identity-verification messages",
    }[category]
    return (
        f"I agree to receive {purpose} from {settings.business_name} on WhatsApp. "
        f"I can opt out at any time."
    )


async def record_consent(
    db: AsyncSession,
    contact: Contact,
    category: str,
    action: str,
    source: str,
    evidence: str,
    actor: str,
    disclosure_text: str = "",
    proof_reference: str = "",
    occurred_at: datetime | None = None,
) -> ConsentEvent:
    category = normalize_category(category)
    if action not in {"granted", "revoked"}:
        raise ValueError("Consent action must be granted or revoked")
    if not evidence.strip():
        raise ValueError("Consent evidence is required")

    event = ConsentEvent(
        contact_id=contact.id,
        category=category,
        action=action,
        business_name=settings.business_name,
        disclosure_text=(disclosure_text or default_disclosure(category)).strip(),
        source=source.strip() or "unknown",
        evidence=evidence.strip(),
        proof_reference=proof_reference.strip() or None,
        privacy_policy_url=settings.privacy_policy_url or None,
        actor=actor,
        occurred_at=occurred_at or datetime.utcnow(),
    )
    db.add(event)

    # Keep the legacy flag as a UI summary of marketing consent only. Broadcast
    # authorization is always determined from the append-only event history.
    if category == "marketing":
        contact.is_opted_in = action == "granted"
        if action == "granted":
            contact.opt_in_source = source
            contact.opt_in_at = datetime.utcnow()
        else:
            contact.opt_out_at = datetime.utcnow()

    await log_event(
        db,
        actor=actor,
        action=f"consent_{action}",
        target_type="contact",
        target_id=contact.id,
        meta={"category": category, "source": source, "proof_reference": proof_reference or None},
    )
    await db.flush()
    return event


async def latest_consent_event(
    db: AsyncSession, contact_id: int, category: str
) -> ConsentEvent | None:
    category = normalize_category(category)
    return (
        await db.execute(
            select(ConsentEvent)
            .where(
                ConsentEvent.contact_id == contact_id,
                ConsentEvent.category == category,
            )
            .order_by(ConsentEvent.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def has_active_consent(db: AsyncSession, contact_id: int, category: str) -> bool:
    latest = await latest_consent_event(db, contact_id, category)
    return latest is not None and latest.action == "granted"


async def eligible_contact_ids(db: AsyncSession, category: str) -> set[int]:
    category = normalize_category(category)
    latest_ids = (
        select(func.max(ConsentEvent.id).label("event_id"))
        .where(ConsentEvent.category == category)
        .group_by(ConsentEvent.contact_id)
        .subquery()
    )
    rows = await db.execute(
        select(ConsentEvent.contact_id)
        .join(latest_ids, ConsentEvent.id == latest_ids.c.event_id)
        .where(ConsentEvent.action == "granted")
    )
    return set(rows.scalars().all())


def template_has_optout(template: MessageTemplate) -> bool:
    if (template.category or "").upper() != "MARKETING":
        return True
    button_text = " ".join(
        str(item.get("text") or item.get("title") or "")
        for item in (template.buttons or [])
        if isinstance(item, dict)
    )
    haystack = " ".join(
        [template.body or "", template.footer or "", button_text]
    ).lower()
    return any(term in haystack for term in ("stop", "unsubscribe", "opt out", "opt-out"))


def validate_business_messaging_configuration() -> None:
    if not settings.privacy_policy_url:
        raise ValueError("Configure a published Privacy Policy URL before sending messages.")
    if not (settings.support_email or settings.support_phone):
        raise ValueError("Configure a customer-support email or phone before sending messages.")


async def validate_broadcast_template(
    db: AsyncSession, template_name: str, language: str
) -> MessageTemplate:
    validate_business_messaging_configuration()
    template = (
        await db.execute(
            select(MessageTemplate).where(MessageTemplate.name == template_name)
        )
    ).scalar_one_or_none()
    if not template:
        raise ValueError("Template does not exist locally. Sync templates from Meta first.")
    if template.status != "APPROVED" or not template.is_active:
        raise ValueError("Template is not currently approved and active.")
    if template.language != language:
        raise ValueError("Template language does not match the approved template.")
    category = (template.category or "").upper()
    if category not in {"MARKETING", "UTILITY"}:
        raise ValueError("Only MARKETING and UTILITY templates may be used for broadcasts.")
    if not template_has_optout(template):
        raise ValueError(
            "Marketing templates must include STOP/opt-out wording or an opt-out button."
        )
    return template


async def marketing_frequency_allowed(
    db: AsyncSession, contact_id: int, exclude_broadcast_id: int | None = None
) -> bool:
    since = datetime.utcnow() - timedelta(days=7)
    query = (
        select(func.count(BroadcastRecipient.id))
        .join(Broadcast, Broadcast.id == BroadcastRecipient.broadcast_id)
        .join(MessageTemplate, MessageTemplate.name == Broadcast.template_name)
        .where(
            BroadcastRecipient.contact_id == contact_id,
            BroadcastRecipient.sent_at >= since,
            BroadcastRecipient.status.in_(["sent", "delivered", "read"]),
            MessageTemplate.category == "MARKETING",
        )
    )
    if exclude_broadcast_id is not None:
        query = query.where(BroadcastRecipient.broadcast_id != exclude_broadcast_id)
    count = (await db.execute(query)).scalar() or 0
    direct_count = (
        await db.execute(
            select(func.count(Message.id))
            .join(Conversation, Conversation.id == Message.conversation_id)
            .join(MessageTemplate, MessageTemplate.name == Message.template_name)
            .where(
                Conversation.contact_id == contact_id,
                Message.created_at >= since,
                MessageTemplate.category == "MARKETING",
            )
        )
    ).scalar() or 0
    return (count + direct_count) < settings.marketing_max_messages_per_7_days


async def revoke_all_consents(
    db: AsyncSession, contact: Contact, source: str, evidence: str, actor: str
) -> None:
    for category in sorted(CONSENT_CATEGORIES):
        if await has_active_consent(db, contact.id, category):
            await record_consent(
                db, contact, category, "revoked", source, evidence, actor
            )


async def reconcile_legacy_marketing_flags(db: AsyncSession) -> None:
    """Make the legacy UI flag reflect evidenced marketing consent only."""
    active_ids = await eligible_contact_ids(db, "marketing")
    contacts = (await db.execute(select(Contact))).scalars().all()
    changed = False
    for contact in contacts:
        expected = contact.id in active_ids
        if contact.is_opted_in != expected:
            contact.is_opted_in = expected
            changed = True
    if changed:
        await db.commit()
