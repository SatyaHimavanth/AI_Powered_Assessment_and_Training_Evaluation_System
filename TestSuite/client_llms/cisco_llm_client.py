import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import openai
import requests
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from pydantic import PrivateAttr


logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


load_dotenv()


class RefreshingAzureChatOpenAI(AzureChatOpenAI):
    """AzureChatOpenAI that retries once after auth refresh on token expiry."""

    _refresh_auth_cb = PrivateAttr(default=None)
    _is_auth_error_cb = PrivateAttr(default=None)

    def configure_auth_refresh(self, refresh_auth_cb, is_auth_error_cb):
        self._refresh_auth_cb = refresh_auth_cb
        self._is_auth_error_cb = is_auth_error_cb
        return self

    def _should_refresh(self, exc: Exception) -> bool:
        return bool(self._is_auth_error_cb and self._is_auth_error_cb(exc))

    def invoke(self, *args, **kwargs):
        try:
            return super().invoke(*args, **kwargs)
        except Exception as exc:
            if not self._should_refresh(exc):
                raise
            logger.warning(f"Auth error detected in invoke(), refreshing token: {type(exc).__name__}")
            self._refresh_auth_cb(self)
            logger.info("Token refreshed successfully, retrying invoke()")
            return super().invoke(*args, **kwargs)

    async def ainvoke(self, *args, **kwargs):
        try:
            return await super().ainvoke(*args, **kwargs)
        except Exception as exc:
            if not self._should_refresh(exc):
                raise
            logger.warning(f"Auth error detected in ainvoke(), refreshing token: {type(exc).__name__}")
            self._refresh_auth_cb(self)
            logger.info("Token refreshed successfully, retrying ainvoke()")
            return await super().ainvoke(*args, **kwargs)

    def stream(self, *args, **kwargs):
        try:
            for chunk in super().stream(*args, **kwargs):
                yield chunk
        except Exception as exc:
            if not self._should_refresh(exc):
                raise
            logger.warning(f"Auth error detected in stream(), refreshing token: {type(exc).__name__}")
            self._refresh_auth_cb(self)
            logger.info("Token refreshed successfully, retrying stream()")
            for chunk in super().stream(*args, **kwargs):
                yield chunk

    async def astream(self, *args, **kwargs):
        try:
            async for chunk in super().astream(*args, **kwargs):
                yield chunk
        except Exception as exc:
            if not self._should_refresh(exc):
                raise
            logger.warning(f"Auth error detected in astream(), refreshing token: {type(exc).__name__}")
            self._refresh_auth_cb(self)
            logger.info("Token refreshed successfully, retrying astream()")
            async for chunk in super().astream(*args, **kwargs):
                yield chunk


class CiscoAzureChatOpenAIProvider:
    """Builds LangChain AzureChatOpenAI clients backed by Cisco OAuth tokens."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        azure_endpoint: Optional[str] = None,
        token_url: Optional[str] = None,
        api_version: Optional[str] = None,
        default_model: Optional[str] = None,
        app_key: Optional[str] = None,
    ) -> None:
        self.client_id = client_id or os.getenv("MBR_AI_CANVAS_Ingest_Client_ID", "")
        self.client_secret = client_secret or os.getenv("MBR_AI_CANVAS_Ingest_Client_Secret", "")
        self.app_key = app_key or os.getenv("MBR_AI_CANVAS_APP_KEY", "")
        self.azure_endpoint = azure_endpoint or os.getenv("MBR_AI_CANVAS_AZURE_ENDPOINT", "https://chat-ai.cisco.com")
        self.token_url = token_url or os.getenv("MBR_AI_CANVAS_SSO_TOKEN_API", "https://id.cisco.com/oauth2/default/v1/token")
        self.api_version = api_version or os.getenv("MBR_AI_CANVAS_AZURE_API_VERSION", "2024-08-01-preview")
        self.default_model = default_model or os.getenv("MBR_AI_CANVAS_AZURE_MODEL", "gpt-4.1")
        self._cached_access_token: Optional[str] = None
        self._token_expires_at_utc: Optional[datetime] = None
        self._refresh_buffer_seconds = 120

    def _request_new_access_token(self) -> tuple[str, Optional[int]]:
        logger.info(f"Requesting new access token from {self.token_url}")
        credentials = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()

        try:
            response = requests.post(
                self.token_url,
                headers={
                    "Accept": "*/*",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": f"Basic {credentials}",
                },
                data="grant_type=client_credentials",
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            token = data.get("access_token")
            if not token:
                raise ValueError("OAuth response did not contain an access token")
            expires_in = data.get("expires_in")
            logger.info(f"Successfully obtained new access token (expires_in={expires_in} seconds)")
            return token, int(expires_in) if isinstance(expires_in, (int, float)) else None
        except Exception as exc:
            logger.error(f"Failed to request new access token: {type(exc).__name__}: {exc}")
            raise

    def _get_valid_access_token(self, force_refresh: bool = False) -> str:
        now = datetime.now(timezone.utc)
        if not force_refresh and (
            self._cached_access_token
            and self._token_expires_at_utc
            and now < self._token_expires_at_utc - timedelta(seconds=self._refresh_buffer_seconds)
        ):
            time_until_expiry = (self._token_expires_at_utc - now).total_seconds()
            logger.debug(f"Using cached access token (expires in {time_until_expiry:.0f} seconds)")
            return self._cached_access_token

        if force_refresh:
            logger.info("Force refresh requested, fetching new token")
        else:
            logger.info("No valid cached token, fetching new token")
        token, expires_in = self._request_new_access_token()
        self._cached_access_token = token
        if expires_in is not None:
            self._token_expires_at_utc = now + timedelta(seconds=expires_in)
        else:
            self._token_expires_at_utc = now + timedelta(minutes=30)
        logger.info(f"Access token cache updated")
        return token

    def _is_auth_error(self, exc: Exception) -> bool:
        if isinstance(exc, openai.AuthenticationError):
            return True
        if isinstance(exc, openai.APIStatusError) and exc.status_code in (401, 403):
            return True
        return False

    def _refresh_llm_auth(self, llm: AzureChatOpenAI) -> None:
        try:
            logger.info("Refreshing LLM authentication with new token")
            new_token = self._get_valid_access_token(force_refresh=True)
            llm.openai_api_key = new_token
            llm.root_client = llm.root_client.with_options(api_key=new_token)
            llm.client = llm.root_client.chat.completions
            if llm.root_async_client is not None:
                llm.root_async_client = llm.root_async_client.with_options(api_key=new_token)
                llm.async_client = llm.root_async_client.chat.completions
            logger.info("LLM authentication refresh completed successfully")
        except Exception as exc:
            logger.error(f"Failed to refresh LLM authentication: {type(exc).__name__}: {exc}")
            raise


    def get_chat_model(
        self,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AzureChatOpenAI:
        """
        Returns a real AzureChatOpenAI object.

        The returned object supports native LangChain methods such as:
        - invoke(...)
        - stream(...)
        - astream(...)
        - batch(...)
        """
        cisco_user_payload = json.dumps({"appkey": self.app_key}, separators=(",", ":"))

        model_kwargs = kwargs.pop("model_kwargs", {})
        model_kwargs.setdefault("user", cisco_user_payload)

        llm = RefreshingAzureChatOpenAI(
            model=model or self.default_model,
            azure_endpoint=self.azure_endpoint,
            azure_ad_token_provider=self._get_valid_access_token,
            api_version=self.api_version,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=0,  # Disable built-in retries to ensure our refresh logic is used
            model_kwargs=model_kwargs,
            **kwargs,
        )
        return llm.configure_auth_refresh(self._refresh_llm_auth, self._is_auth_error)


if __name__ == "__main__":
    provider = CiscoAzureChatOpenAIProvider()
    llm = provider.get_chat_model(model="gpt-4o-mini")

    # Uses native LangChain invoke method.
    response = llm.invoke("Say hello in one short sentence.")
    print(response.content)
