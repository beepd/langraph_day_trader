import os

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# To switch model, change these two lines (or set LLM_PROVIDER and LLM_MODEL in .env).
# Providers: "gemini", "groq", "mistral", "openrouter"
# ---------------------------------------------------------------------------
PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")

# Each provider reads its own key from .env:
#   gemini -> GOOGLE_API_KEY    groq -> GROQ_API_KEY
#   mistral -> MISTRAL_API_KEY  openrouter -> OPENROUTER_API_KEY


def build_llm(provider: str = PROVIDER, model: str = MODEL):
    """Create the chat model. Packages are imported only for the provider you actually use."""
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model, temperature=0, google_api_key=os.getenv("GOOGLE_API_KEY"))
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=model, temperature=0, api_key=os.getenv("GROQ_API_KEY"))
    if provider == "mistral":
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI(model=model, temperature=0, api_key=os.getenv("MISTRAL_API_KEY"))
    if provider == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, temperature=0, api_key=os.getenv("OPENROUTER_API_KEY"),
                          base_url="https://openrouter.ai/api/v1")
    raise ValueError(f"Unknown provider '{provider}'. Use gemini, groq, mistral or openrouter.")