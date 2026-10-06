import os

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# To switch model, change these two lines (or set LLM_PROVIDER and LLM_MODEL in .env).
# Providers: "gemini", "openai", "groq", "mistral", "openrouter"
# ---------------------------------------------------------------------------
PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")

# Each provider reads its own key from .env:
#   gemini -> GOOGLE_API_KEY      openai -> OPENAI_API_KEY      groq -> GROQ_API_KEY
#   mistral -> MISTRAL_API_KEY    openrouter -> OPENROUTER_API_KEY


def _temperature_options(model: str) -> dict:
    """We ask for temperature 0 (the most consistent answers). Some 'reasoning' models (the gpt-5 and o-series)
    refuse any value except their own default, so for those we leave it out.
    You can override this in .env: LLM_TEMPERATURE=0.2 sets it, LLM_TEMPERATURE= (empty) leaves it out."""
    setting = os.getenv("LLM_TEMPERATURE")
    if setting is not None:
        return {"temperature": float(setting)} if setting.strip() else {}
    if model.startswith(("gpt-5", "o1", "o3", "o4")):
        return {}
    return {"temperature": 0}


def build_llm(provider: str = PROVIDER, model: str = MODEL):
    """Create the chat model. Packages are imported only for the provider you actually use."""
    options = _temperature_options(model)
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model, google_api_key=os.getenv("GOOGLE_API_KEY"), **options)
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, api_key=os.getenv("OPENAI_API_KEY"), **options)
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=model, api_key=os.getenv("GROQ_API_KEY"), **options)
    if provider == "mistral":
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI(model=model, api_key=os.getenv("MISTRAL_API_KEY"), **options)
    if provider == "openrouter":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, api_key=os.getenv("OPENROUTER_API_KEY"),
                          base_url="https://openrouter.ai/api/v1", **options)
    raise ValueError(f"Unknown provider '{provider}'. Use gemini, openai, groq, mistral or openrouter.")