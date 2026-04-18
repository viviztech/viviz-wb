import anthropic
from app.config import settings

_client = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _client


async def generate_reply(
    user_message: str,
    contact_name: str = "Customer",
    conversation_history: list[dict] | None = None,
    system_context: str = "",
) -> str:
    """Generate a WhatsApp reply using Claude Opus 4.7 with prompt caching."""
    client = get_client()

    system_prompt = f"""You are a helpful WhatsApp business assistant for Viviz Technologies.
You respond in a friendly, professional, and concise manner suitable for WhatsApp messaging.
Keep responses under 200 words. Use simple formatting (no markdown headers).
The customer's name is {contact_name}.
{system_context}"""

    messages = []
    if conversation_history:
        for msg in conversation_history[-10:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_message})

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=messages,
    )
    return response.content[0].text


async def classify_intent(message: str) -> str:
    """Classify message intent for routing."""
    client = get_client()
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=50,
        system=[{
            "type": "text",
            "text": "Classify user intent into ONE word: support, sales, inquiry, greeting, complaint, feedback, other. Reply with only the word.",
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": message}],
    )
    return response.content[0].text.strip().lower()


async def summarize_conversation(messages: list[dict]) -> str:
    """Summarize a conversation for quick reference."""
    client = get_client()
    text = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": f"Summarize this WhatsApp conversation in 2-3 sentences:\n\n{text}"
        }],
    )
    return response.content[0].text
