import os
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from dotenv import load_dotenv
from pydantic import BaseModel

# Load backend/.env if present
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)
else:
    load_dotenv()


class LLMError(Exception):
    """Base exception for LLM provider errors."""
    pass


class LLMConfigurationError(LLMError):
    """Raised when provider configuration or credentials are missing."""
    pass


class LLMTimeoutError(LLMError):
    """Raised when an LLM request times out."""
    pass


class LLMProviderError(LLMError):
    """Raised when the LLM provider returns an HTTP error status."""
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class LLMResponse(BaseModel):
    """Normalized response from an LLM provider."""
    content: str
    model: str
    provider: str
    is_mock: bool = False
    usage: Optional[Dict[str, Any]] = None
    latency_ms: Optional[float] = None


class BaseLLMProvider(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        """Generate a chat completion from conversation messages and system prompt."""
        pass


class OpenAICompatibleLLMProvider(BaseLLMProvider):
    """
    Standard provider implementation for OpenAI-compatible endpoints,
    such as Nebius Token Inference and NVIDIA NIM API Catalog.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        provider_name: str = "openai_compatible",
        timeout: float = 30.0,
    ):
        if not api_key:
            raise LLMConfigurationError(f"API key must be provided for {provider_name} inference.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.provider_name = provider_name
        self.timeout = timeout

    def _redact(self, text: str) -> str:
        """Redact sensitive API key from logs and error messages."""
        if not text or not self.api_key:
            return text or ""
        return re.sub(re.escape(self.api_key), "[REDACTED_API_KEY]", str(text))

    def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        t0 = time.perf_counter()
        req_timeout = timeout or self.timeout
        endpoint = f"{self.base_url}/chat/completions"

        full_messages = [{"role": "system", "content": system_prompt}] + messages
        payload = {
            "model": self.model,
            "messages": full_messages,
            "temperature": 0.2,
            "max_tokens": 1024,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=req_timeout) as client:
                resp = client.post(endpoint, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                choices = data.get("choices")
                if not choices or not isinstance(choices, list):
                    raise LLMProviderError(f"Malformed response from {self.provider_name}: no completion choices returned.")

                choice = choices[0]
                message_obj = choice.get("message")
                if not message_obj or not isinstance(message_obj, dict):
                    raise LLMProviderError(f"Malformed response from {self.provider_name}: message payload missing in choice.")

                raw_content = message_obj.get("content")
                content = (raw_content or "").strip()
                usage = data.get("usage")
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

                return LLMResponse(
                    content=content,
                    model=self.model,
                    provider=self.provider_name,
                    is_mock=False,
                    usage=usage,
                    latency_ms=latency_ms,
                )
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"Request to {self.provider_name} timed out after {req_timeout}s.") from e
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            msg = self._redact(e.response.text)
            raise LLMProviderError(f"{self.provider_name} returned HTTP {status}: {msg}", status_code=status) from e
        except LLMError:
            raise
        except Exception as e:
            clean_err = self._redact(str(e))
            raise LLMProviderError(f"Connection failure to {self.provider_name}: {clean_err}") from e


class MockLLMProvider(BaseLLMProvider):
    """
    Clearly labeled local mock provider for development and testing.
    Provides context-aware synthesized responses without needing external credits.
    """

    def __init__(self, model_name: str = "mock-privatemind-v1"):
        self.model = model_name
        self.provider_name = "mock"

    def generate(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        t0 = time.perf_counter()
        last_message = messages[-1]["content"] if messages else ""
        lower = last_message.lower()

        # Parse any memory entries inside system_prompt
        # Regex to capture facts from `<memory id="...">\n  Title: ...\n  Fact: ...\n</memory>`
        memory_matches = re.findall(
            r'<memory id="(\d+)" category="([^"]+)" relevance="([^"]+)">\s*Title:\s*([^\n]+)\s*Fact:\s*([^\n]+)',
            system_prompt,
            re.DOTALL,
        )

        response_lines: List[str] = []

        if memory_matches:
            # Memory-aware response using the top matching memories
            facts_summary = []
            citations = []
            for m_id, cat, rel, title, fact in memory_matches[:3]:
                facts_summary.append(f"{fact.strip()} (from '{title.strip()}', category: {cat})")
                citations.append(f"Memory #{m_id}")

            if "hardware" in lower or "esp32" in lower or "sensor" in lower:
                response_lines.append(
                    f"Based on your stored context ({', '.join(citations)}), you are utilizing ESP32 sensors for your water quality monitoring project."
                )
            elif "learn" in lower or "skill" in lower or "python" in lower:
                response_lines.append(
                    f"According to your memory records ({', '.join(citations)}), you are currently learning and developing proficiency in Python."
                )
            elif "diet" in lower or "food" in lower or "eat" in lower:
                response_lines.append(
                    f"Your context indicates ({', '.join(citations)}) that you follow a vegetarian dietary preference with reduced sugar."
                )
            elif "project" in lower:
                response_lines.append(
                    f"According to your stored projects ({', '.join(citations)}): {' '.join(facts_summary)}"
                )
            else:
                response_lines.append(
                    f"Based on your approved memories ({', '.join(citations)}): {' '.join(facts_summary)}"
                )
        else:
            # Explicitly state when no matching memory exists
            response_lines.append(
                "I do not have any saved memory regarding this subject in your context vault. I'm ready to help you answer or record new details."
            )

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return LLMResponse(
            content="\n\n".join(response_lines),
            model=self.model,
            provider="mock",
            is_mock=True,
            usage={"prompt_tokens": 150, "completion_tokens": 40, "total_tokens": 190},
            latency_ms=latency_ms,
        )


def get_llm_provider() -> BaseLLMProvider:
    """
    Factory that instantiates the configured LLM provider from environment variables.
    Supports Nebius, NVIDIA NIM, OpenAI-compatible, and Mock fallback.
    """
    # Ensure latest environment from backend/.env is picked up
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE, override=False)

    provider_type = os.getenv("LLM_PROVIDER", "").strip().lower()
    timeout = float(os.getenv("LLM_TIMEOUT", "30.0"))

    # Check for Nebius
    if provider_type == "nebius":
        api_key = os.getenv("NEBIUS_API_KEY") or os.getenv("LLM_API_KEY")
        if not api_key:
            raise LLMConfigurationError(
                "LLM_PROVIDER is configured as 'nebius', but no NEBIUS_API_KEY was found in environment. "
                "Please configure NEBIUS_API_KEY in backend/.env or set LLM_PROVIDER=mock."
            )
        base_url = os.getenv("LLM_BASE_URL", "https://api.studio.nebius.ai/v1")
        model = os.getenv("LLM_MODEL", "meta-llama/Meta-Llama-3.1-70B-Instruct")
        return OpenAICompatibleLLMProvider(
            api_key=api_key,
            base_url=base_url,
            model=model,
            provider_name="nebius",
            timeout=timeout,
        )

    # Check for NVIDIA NIM
    if provider_type == "nvidia":
        api_key = os.getenv("NVIDIA_API_KEY") or os.getenv("LLM_API_KEY")
        if not api_key:
            raise LLMConfigurationError(
                "LLM_PROVIDER is configured as 'nvidia', but no NVIDIA_API_KEY was found in environment. "
                "Please configure NVIDIA_API_KEY in backend/.env or set LLM_PROVIDER=mock."
            )
        base_url = os.getenv("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")
        model = os.getenv("LLM_MODEL", "meta/llama-3.1-70b-instruct")
        return OpenAICompatibleLLMProvider(
            api_key=api_key,
            base_url=base_url,
            model=model,
            provider_name="nvidia",
            timeout=timeout,
        )

    # Custom OpenAI-compatible provider with API key
    if provider_type in ["openai", "custom"]:
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
        if not api_key:
            raise LLMConfigurationError(
                f"LLM_PROVIDER is configured as '{provider_type}', but no OPENAI_API_KEY or LLM_API_KEY was found in environment."
            )
        base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        return OpenAICompatibleLLMProvider(
            api_key=api_key,
            base_url=base_url,
            model=model,
            provider_name=provider_type,
            timeout=timeout,
        )

    # Explicit or empty mock provider fallback
    if provider_type in ["mock", ""]:
        return MockLLMProvider()

    # Reject unknown provider types explicitly
    raise LLMConfigurationError(
        f"Unsupported LLM_PROVIDER '{provider_type}'. Supported providers are: 'mock', 'nebius', 'nvidia', 'openai'."
    )
