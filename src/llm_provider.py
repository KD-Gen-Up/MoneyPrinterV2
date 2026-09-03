from urllib.parse import urlparse

import ollama

from config import get_ollama_base_url

_selected_model: str | None = None


def _validate_ollama_url(url: str) -> str:
    value = str(url).strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Ollama base URL must be a valid HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("Ollama base URL must not contain embedded credentials")
    return value


def _client() -> ollama.Client:
    return ollama.Client(host=_validate_ollama_url(get_ollama_base_url()))


def list_models() -> list[str]:
    response = _client().list()
    return sorted(m.model for m in response.models)


def select_model(model: str) -> None:
    value = str(model or "").strip()
    if not value or any(ch in value for ch in "\r\n"):
        raise ValueError("Ollama model name cannot be empty or contain newlines")
    global _selected_model
    _selected_model = value


def get_active_model() -> str | None:
    return _selected_model


def generate_text(prompt: str, model_name: str = None) -> str:
    model = str(model_name).strip() if model_name else _selected_model
    if not model:
        raise RuntimeError("No Ollama model selected. Call select_model() first or pass model_name.")
    if "\r" in model or "\n" in model:
        raise ValueError("Invalid Ollama model name")

    response = _client().chat(
        model=model,
        messages=[{"role": "user", "content": str(prompt)}],
    )
    content = response.get("message", {}).get("content", "")
    if not isinstance(content, str):
        raise RuntimeError("Ollama returned an invalid response")
    return content.strip()
