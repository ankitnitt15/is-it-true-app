import os

DAILY_USER_CAP = int(os.getenv("DAILY_USER_CAP", "5"))
GLOBAL_DAILY_CALL_CAP = int(os.getenv("GLOBAL_DAILY_CALL_CAP", "500"))
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "3000"))

# Comma-separated list -- the hosted frontend's origin plus, once loaded,
# the browser extension's chrome-extension://<id> origin.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5500").split(",")
    if origin.strip()
]

MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(5 * 1024 * 1024)))  # 5MB
ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}

# Longest side, in px, before an uploaded image gets downscaled -- large
# phone-camera photos are slower to upload and for Gemini to process; this
# resizes (never recompresses) anything past this without touching images
# that are already a reasonable size.
MAX_IMAGE_DIMENSION = int(os.getenv("MAX_IMAGE_DIMENSION", "1600"))

# An image-bearing Gemini call costs meaningfully more tokens than a
# text-only one -- add this flat extra weight to the global daily counter
# whenever a request includes an image, so GLOBAL_DAILY_CALL_CAP still
# tracks real spend rather than just call count.
IMAGE_CALL_WEIGHT = int(os.getenv("IMAGE_CALL_WEIGHT", "4"))

# Cross-site cookies (frontend and backend on different domains, e.g. Vercel +
# Render) need SameSite=None + Secure, which in turn requires HTTPS. For local
# dev over plain http://localhost, leave these at their defaults.
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# Shared secret for GET /admin/stats -- unset by default so the endpoint is
# effectively disabled (returns 404) until you deliberately turn it on.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
