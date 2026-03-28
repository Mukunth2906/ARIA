"""
Initialises the LLM via LangChain.
Supports:
  1. GITHUB_TOKEN   — GitHub Models endpoint (openai/gpt-4.1)
  2. GEMINI_API_KEY — Google Generative AI (gemini-1.5-flash / gemini-2.0-flash)
  3. OPENAI_API_KEY — OpenAI API (gpt-4o-mini / gpt-4o)

Always loads credentials from environment — never hardcoded.
"""
import os
from dotenv import load_dotenv

load_dotenv()

_llm_instance = None


def get_llm():
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance

    if os.getenv("GITHUB_TOKEN"):
        from langchain_openai import ChatOpenAI
        _llm_instance = ChatOpenAI(
            model="openai/gpt-4.1",
            api_key=os.getenv("GITHUB_TOKEN"),
            base_url="https://models.github.ai/inference/v1",
            temperature=0.2,
            max_tokens=512,
            max_retries=3,
        )
    elif os.getenv("GEMINI_API_KEY"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        _llm_instance = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=os.getenv("GEMINI_API_KEY"),
            temperature=0.2,
            max_output_tokens=512,
        )
    elif os.getenv("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI
        _llm_instance = ChatOpenAI(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=os.getenv("OPENAI_API_KEY"),
            temperature=0.2,
            max_tokens=512,
        )
    else:
        raise EnvironmentError(
            "No LLM API key configured in .env!\n"
            "Please add at least one of the following to your .env file:\n"
            "  - GITHUB_TOKEN (Personal Access Token from https://github.com/settings/tokens)\n"
            "  - GEMINI_API_KEY (from https://aistudio.google.com/app/apikey)\n"
            "  - OPENAI_API_KEY (from https://platform.openai.com/api-keys)"
        )

    return _llm_instance

