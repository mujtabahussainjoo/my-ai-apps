"""Canonical identity of the order a human approved."""

import hashlib
import json


def order_fingerprint(request):
    fields = request.model_dump(mode="json", exclude={"idempotency_key"})
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
