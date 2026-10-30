"""Feature extraction for the on-the-fly ML strategy.

Design rules
------------
* Features describe a CANDIDATE PAYLOAD only. They are computed before the request is sent, so
  they can never contain anything about the response (the old ``len_deviation`` compared the
  request size with response sizes, which was meaningless, and has been removed).
* Features are PER FIELD. A quote in ``username`` and a quote in ``query`` behave differently on
  a validation-aware target, so the model must be able to tell which field was changed.
* Features are about *validity-shaped* properties (looks like an email, starts with an
  ``OPERATION:`` token, is numeric, ...) as well as attack-shaped ones, because the project's
  hypothesis is that useful payloads must pass validation before they reach the sink.
* Nothing here is specific to one target: the field names come from the seed request.
"""
from __future__ import annotations

import math
import re

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_OP_PREFIX_RE = re.compile(r"^[A-Za-z_]+:")
_SQL_KEYWORDS = ("select", "union", "insert", "update", "delete", "drop", "or 1", "' or", "--", ";")
_QUOTES = "'\""

# Per-field feature names, in the order produced by ``_field_features``.
_FIELD_FEATURES = (
    "present",        # field exists in the payload
    "is_str",         # value is a string (0 for None / int / list / dict / bool / float)
    "log_len",        # log(1 + len(text))
    "changed",        # differs from the seed value
    "n_special",      # non-alphanumeric, non-space characters
    "n_digit",
    "has_at",
    "has_colon",
    "has_quote",
    "has_ctrl",       # NUL or other control characters
    "has_sql",        # SQL keyword / comment fragment
    "email_like",     # fully matches a simple email shape
    "op_prefix",      # starts with an ``OPERATION:`` style token
    "is_numeric",     # value is a decimal integer string
    "is_empty",
)
_GLOBAL_FEATURES = ("n_changed", "n_missing", "n_non_str")


def feature_names(seed_request: dict) -> list[str]:
    """Names matching the vector returned by :func:`extract_features` for this seed."""
    names = [f"{k}.{f}" for k in sorted(seed_request) for f in _FIELD_FEATURES]
    return names + list(_GLOBAL_FEATURES)


def _field_features(value, present: bool, seed_value) -> list[float]:
    if not present:
        return [0.0] * len(_FIELD_FEATURES)
    is_str = isinstance(value, str)
    text = value if is_str else str(value)
    low = text.lower()
    return [
        1.0,
        float(is_str),
        math.log1p(len(text)),
        float(value != seed_value),
        float(sum(1 for c in text if not c.isalnum() and not c.isspace())),
        float(sum(1 for c in text if c.isdigit())),
        float("@" in text),
        float(":" in text),
        float(any(q in text for q in _QUOTES)),
        float(any(ord(c) < 32 for c in text)),
        float(any(kw in low for kw in _SQL_KEYWORDS)),
        float(bool(_EMAIL_RE.match(text))),
        float(bool(_OP_PREFIX_RE.match(text))),
        float(text.isdigit()),
        float(len(text) == 0),
    ]


def extract_features(payload: dict, seed_request: dict) -> list[float]:
    """Return a fixed-length numeric vector for ``payload`` (length = len(feature_names(seed)))."""
    vec: list[float] = []
    n_changed = n_missing = n_non_str = 0
    for key in sorted(seed_request):
        present = key in payload
        value = payload.get(key)
        seed_value = seed_request[key]
        vec.extend(_field_features(value, present, seed_value))
        if not present:
            n_missing += 1
        else:
            n_changed += int(value != seed_value)
            n_non_str += int(not isinstance(value, str))
    vec.extend([float(n_changed), float(n_missing), float(n_non_str)])
    return vec
