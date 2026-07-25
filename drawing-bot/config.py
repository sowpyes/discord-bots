# Verified against GET https://image.pollinations.ai/models on 2026-07-25.
# Only add a model here after confirming it actually changes provider output --
# the legacy endpoint silently ignores unknown model values instead of erroring,
# so this list is the only thing standing between a user request and a wrong result.
ALLOWED_MODELS = ["sana"]
DEFAULT_MODEL = "sana"

# Requested width/height sent to the provider. The legacy endpoint does NOT honor
# these exactly -- it scales to a fixed total-pixel budget (~768x768) while
# preserving aspect ratio. Sent as-is anyway; the reply always reports the real
# decoded image size, never these nominal values.
RATIO_SIZES = {
    "square": (1024, 1024),
    "portrait": (768, 1024),
    "landscape": (1024, 768),
}
DEFAULT_RATIO = "square"

MAX_PROMPT_LENGTH = 500
USER_COOLDOWN_SECONDS = 20
MAX_CONCURRENT_GENERATIONS = 1  # matches Pollinations' own "max 1 queued request per IP" limit
GENERATION_TIMEOUT_SECONDS = 60
