from __future__ import annotations


PROFILE_SOURCES = frozenset(
    {
        "env",
        "locals",
        "hermes_home",
        "fallback_default",
        "sanitized_env",
        "sanitized_locals",
        "sanitized_hermes_home",
    }
)

PROFILE_SOURCE_FALLBACK = "fallback_default"
