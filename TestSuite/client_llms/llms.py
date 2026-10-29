"""Opt-in test provider; importing this module never authenticates or calls an LLM."""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel

from .cisco_llm_client import CiscoAzureChatOpenAIProvider


@lru_cache(maxsize=1)
def get_chat_model() -> BaseChatModel:
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    required = (
        "MBR_AI_CANVAS_Ingest_Client_ID",
        "MBR_AI_CANVAS_Ingest_Client_Secret",
        "MBR_AI_CANVAS_APP_KEY",
    )
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing test client configuration: {', '.join(missing)}")
    provider = CiscoAzureChatOpenAIProvider()
    return provider.get_chat_model(
        model=os.getenv("MBR_AI_CANVAS_AZURE_MODEL_4_1") or provider.default_model,
        timeout=60,
    )
