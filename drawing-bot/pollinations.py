import hashlib
import io
import logging
import time
from dataclasses import dataclass
from urllib.parse import quote

import aiohttp
from PIL import Image

import config

logger = logging.getLogger("drawing-bot")

POLLINATIONS_BASE_URL = "https://image.pollinations.ai/prompt"


class GenerationError(Exception):
    """Base class for errors that should be shown to the user as a plain message."""

    def __init__(self, user_message: str):
        self.user_message = user_message
        super().__init__(user_message)


class PromptTooLongError(GenerationError):
    pass


class InvalidModelError(GenerationError):
    pass


class CooldownError(GenerationError):
    pass


class ConcurrencyLimitError(GenerationError):
    pass


class ProviderError(GenerationError):
    pass


class ProviderTimeoutError(GenerationError):
    pass


class NonImageContentError(GenerationError):
    pass


@dataclass
class GenerationResult:
    image_bytes: bytes
    content_type: str
    extension: str
    width: int
    height: int
    model: str
    seed: int
    elapsed_seconds: float
    sha256_prefix: str


def validate_prompt(prompt: str) -> None:
    if not prompt or not prompt.strip():
        raise GenerationError("提示詞不可為空。")
    if len(prompt) > config.MAX_PROMPT_LENGTH:
        raise PromptTooLongError(
            f"提示詞長度 {len(prompt)} 超過上限 {config.MAX_PROMPT_LENGTH} 字元，請縮短後再試。"
        )


def validate_model(model: str | None) -> str:
    if model is None:
        return config.DEFAULT_MODEL
    if model not in config.ALLOWED_MODELS:
        allowed = "、".join(config.ALLOWED_MODELS)
        raise InvalidModelError(f"模型「{model}」不在允許清單中。目前允許的模型：{allowed}")
    return model


def resolve_ratio(ratio: str) -> tuple[int, int]:
    return config.RATIO_SIZES.get(ratio, config.RATIO_SIZES[config.DEFAULT_RATIO])


class CooldownTracker:
    def __init__(self, cooldown_seconds: float):
        self.cooldown_seconds = cooldown_seconds
        self._last_use: dict[int, float] = {}

    def check(self, user_id: int) -> None:
        last = self._last_use.get(user_id)
        if last is None:
            return
        remaining = self.cooldown_seconds - (time.monotonic() - last)
        if remaining > 0:
            raise CooldownError(f"冷卻中，請再等 {remaining:.1f} 秒後再試。")

    def mark(self, user_id: int) -> None:
        self._last_use[user_id] = time.monotonic()


class ConcurrencyGate:
    """Non-blocking slot counter -- rejects immediately instead of queuing when at capacity."""

    def __init__(self, limit: int):
        self.limit = limit
        self.active = 0

    def try_acquire(self) -> bool:
        if self.active >= self.limit:
            return False
        self.active += 1
        return True

    def release(self) -> None:
        self.active = max(0, self.active - 1)


cooldown_tracker = CooldownTracker(config.USER_COOLDOWN_SECONDS)
concurrency_gate = ConcurrencyGate(config.MAX_CONCURRENT_GENERATIONS)


async def generate_image(
    prompt: str,
    ratio: str,
    model: str | None,
    seed: int,
    private: bool,
) -> GenerationResult:
    """Calls the Pollinations legacy endpoint once. No retries on failure."""
    resolved_model = validate_model(model)
    width, height = resolve_ratio(ratio)

    url = f"{POLLINATIONS_BASE_URL}/{quote(prompt, safe='')}"
    params = {
        "width": str(width),
        "height": str(height),
        "seed": str(seed),
        "model": resolved_model,
        "nologo": "true",
        "private": "true" if private else "false",
    }

    start = time.monotonic()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=config.GENERATION_TIMEOUT_SECONDS)
            ) as resp:
                elapsed = time.monotonic() - start
                content_type = resp.headers.get("Content-Type", "")

                if resp.status != 200:
                    body_preview = (await resp.read())[:200]
                    logger.error(
                        "Pollinations API returned status %d (elapsed=%.2fs): %r",
                        resp.status, elapsed, body_preview,
                    )
                    raise ProviderError("圖片生成失敗，請稍後再試。")

                if not content_type.startswith("image/"):
                    body_preview = (await resp.read())[:200]
                    logger.error(
                        "Pollinations API returned non-image content-type=%s (elapsed=%.2fs): %r",
                        content_type, elapsed, body_preview,
                    )
                    raise NonImageContentError("圖片生成失敗（伺服器回傳非圖片內容），請稍後再試。")

                image_bytes = await resp.read()
    except TimeoutError as exc:
        logger.exception("Pollinations API request timed out (elapsed=%.2fs)", time.monotonic() - start)
        raise ProviderTimeoutError("圖片生成逾時，請稍後再試。") from exc
    except GenerationError:
        raise
    except Exception as exc:
        logger.exception("Error while requesting Pollinations API")
        raise ProviderError("發生錯誤，請稍後再試。") from exc

    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            actual_width, actual_height = im.size
    except Exception as exc:
        logger.exception("Failed to decode returned image bytes")
        raise NonImageContentError("圖片生成失敗（無法解析回傳的圖片），請稍後再試。") from exc

    extension = "png" if content_type == "image/png" else "jpg"
    sha256_prefix = hashlib.sha256(image_bytes).hexdigest()[:12]

    return GenerationResult(
        image_bytes=image_bytes,
        content_type=content_type,
        extension=extension,
        width=actual_width,
        height=actual_height,
        model=resolved_model,
        seed=seed,
        elapsed_seconds=elapsed,
        sha256_prefix=sha256_prefix,
    )
