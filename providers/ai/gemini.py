"""Minimal Gemini API client: list models and generate JSON that follows a schema.

Uses the REST endpoint directly (https://generativelanguage.googleapis.com/v1beta)
so the only dependency is httpx. The key is sent in the x-goog-api-key header,
never in the URL, so it can't end up in logs.
"""

import base64
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT_SECONDS = 180
RETRY_STATUSES = (429, 500, 502, 503, 504)
RETRY_WAITS = (3, 10)


class GeminiError(Exception):
    """A Gemini problem with a message fit to show the user."""


class GeminiQuotaError(GeminiError):
    """The key's plan has no quota at all for the model (e.g. image models on the free tier)."""


class Gemini:
    def __init__(self, api_key: str, model: Optional[str] = None, transport: httpx.BaseTransport = None):
        if not api_key:
            raise GeminiError("No Gemini API key is set.")
        self.model = model
        self._client = httpx.Client(base_url=BASE_URL, headers={"x-goog-api-key": api_key}, timeout=TIMEOUT_SECONDS, transport=transport)

    def list_models(self) -> List[Dict[str, str]]:
        """Models this key can use for text generation, as {"id", "name"}."""
        data = self._request("GET", "/models", params={"pageSize": 200})
        return [
            {"id": m["name"].split("/", 1)[-1], "name": m.get("displayName", m["name"])}
            for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]

    def generate_json(self, prompt: str, schema: Dict[str, Any], system: str = "", temperature: float = 0.9) -> Any:
        """Generate a reply constrained to `schema` (OpenAPI-style) and return it parsed."""
        if not self.model:
            raise GeminiError("No Gemini model is selected.")
        body: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema, "temperature": temperature},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        data = self._request("POST", f"/models/{self.model}:generateContent", json=body)

        blocked = data.get("promptFeedback", {}).get("blockReason")
        if blocked:
            raise GeminiError(f"Gemini refused the request ({blocked}). Rephrase the topic.")
        candidates = data.get("candidates") or []
        if not candidates:
            raise GeminiError("Gemini returned no answer. Try again.")
        candidate = candidates[0]
        text = "".join(p.get("text", "") for p in candidate.get("content", {}).get("parts", []) if not p.get("thought"))
        reason = candidate.get("finishReason", "STOP")
        if reason == "MAX_TOKENS":
            raise GeminiError("Gemini's answer was cut off because it was too long. Ask for fewer videos at once.")
        if reason in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"):
            raise GeminiError(f"Gemini stopped for safety reasons ({reason}). Rephrase the topic.")
        try:
            return json.loads(text)
        except ValueError:
            raise GeminiError("Gemini's answer wasn't valid JSON. Try again.")

    def generate_image(self, prompt: str, aspect_ratio: str = "1:1", model: Optional[str] = None) -> bytes:
        """Draw one image with an image model and return its bytes (PNG or JPEG)."""
        model = model or self.model
        if not model:
            raise GeminiError("No Gemini image model is available to this key.")
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect_ratio}},
        }
        data = self._request("POST", f"/models/{model}:generateContent", json=body)
        blocked = data.get("promptFeedback", {}).get("blockReason")
        if blocked:
            raise GeminiError(f"Gemini refused to draw that ({blocked}). Change the idea.")
        for candidate in data.get("candidates") or []:
            for part in candidate.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or {}
                if inline.get("data") and not part.get("thought"):
                    return base64.b64decode(inline["data"])
        raise GeminiError("Gemini didn't return an image. Try again or change the idea.")

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        for attempt in range(len(RETRY_WAITS) + 1):
            try:
                res = self._client.request(method, path, **kwargs)
            except httpx.HTTPError as e:
                if attempt < len(RETRY_WAITS):
                    time.sleep(RETRY_WAITS[attempt])
                    continue
                raise GeminiError(f"Couldn't reach Gemini: {e}")
            # A zero quota (the free tier on image models) never clears by waiting.
            no_quota = res.status_code == 429 and "limit: 0" in res.text
            if res.status_code in RETRY_STATUSES and attempt < len(RETRY_WAITS) and not no_quota:
                time.sleep(RETRY_WAITS[attempt])
                continue
            if res.status_code >= 400:
                raise _error(res)
            return res.json()
        raise GeminiError("Gemini kept failing; try again later.")


def _error(res: httpx.Response) -> GeminiError:
    try:
        err = res.json().get("error", {})
        message, status = err.get("message", ""), err.get("status", "")
    except ValueError:
        message, status = res.text[:200], ""
    if res.status_code == 400 and "API key" in message:
        return GeminiError("The Gemini API key isn't valid. Check it in Settings.")
    if res.status_code == 403:
        return GeminiError("This Gemini API key isn't allowed to use the Gemini API. Check the key's restrictions in Google AI Studio.")
    if res.status_code == 404:
        return GeminiError("That Gemini model isn't available to this key. Pick another model in Settings.")
    if res.status_code == 429 and "limit: 0" in message:
        return GeminiQuotaError("This Gemini key's plan doesn't include this model (its free-tier limit is 0). Turn on billing in Google AI Studio to use it.")
    if res.status_code == 429:
        return GeminiError("Gemini's rate limit or quota is used up. Wait a minute and try again.")
    return GeminiError(f"Gemini error {res.status_code} {status}: {message}".strip())


def pick_default_model(models: List[Dict[str, str]]) -> Optional[str]:
    """Newest stable Flash-Lite model: the cheapest that writes short structured scripts well
    (and it doesn't spend tokens on thinking). Plain Flash is the fallback."""
    def version(model_id: str, suffix: str):
        m = re.match(rf"gemini-(\d+)(?:\.(\d+))?-{suffix}$", model_id)
        return (int(m.group(1)), int(m.group(2) or 0)) if m else None

    for suffix in ("flash-lite", "flash"):
        stable = [(version(m["id"], suffix), m["id"]) for m in models if version(m["id"], suffix)]
        if stable:
            return max(stable)[1]
    flash = [m["id"] for m in models if "flash" in m["id"] and not re.search(r"lite|image|tts|audio|live|embed|thinking", m["id"])]
    return flash[0] if flash else (models[0]["id"] if models else None)


def pick_image_model(models: List[Dict[str, str]]) -> Optional[str]:
    """Newest stable Flash image model (cheaper than Pro); a preview or Pro one only if nothing else."""
    def rank(model_id: str):
        m = re.match(r"gemini-(\d+)(?:\.(\d+))?-(flash|flash-lite|pro)-image(-preview)?$", model_id)
        if not m:
            return None
        return (m.group(4) is None, m.group(3) == "flash", int(m.group(1)), int(m.group(2) or 0))

    ranked = [(rank(m["id"]), m["id"]) for m in models if rank(m["id"])]
    return max(ranked)[1] if ranked else None
