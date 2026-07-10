from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from hermes_feishu_card.diagnostics import (
    DiagnosticFinding,
    DiagnosticReport,
    build_diagnostic_report,
    build_route_chain,
)
from hermes_feishu_card.install.detect import HermesDetection
from hermes_feishu_card.install.recovery import RecoveryPlan


def _detection(tmp_path: Path) -> HermesDetection:
    root = tmp_path / "private" / "hermes"
    return HermesDetection(
        root=root,
        version="0.17.0",
        version_source="VERSION",
        minimum_version="v2026.4.23",
        run_py=root / "gateway" / "run.py",
        run_py_exists=True,
        supported=True,
        reason="supported",
        hook_strategy="gateway_run_013_plus",
        compatibility="full",
        capabilities={"message_handler": True},
    )


def _recovery_plan(tmp_path: Path, *, state: str = "installed") -> RecoveryPlan:
    return RecoveryPlan(
        root=tmp_path / "private" / "hermes",
        state=state,
        executable=state not in {"installed", "refused"},
        fingerprint="a" * 64,
        actions=("repair_gateway",) if state != "installed" else (),
        findings=(),
    )


def _report(tmp_path: Path, **overrides: object) -> DiagnosticReport:
    values: dict[str, object] = {
        "status": "warning",
        "created_at": 100.0,
        "config": {"path": str(tmp_path / "private" / "config.yaml")},
        "hermes": {"root": str(tmp_path / "private" / "hermes")},
        "streaming": {"status": "enabled"},
        "install_state": {"status": "installed", "recovery_state": "installed"},
        "routing": {
            "profile_id": "work",
            "chat_id": "oc_secret_chat",
            "operator_open_id": "ou_secret_operator",
        },
        "runtime": {},
        "findings": (),
    }
    values.update(overrides)
    return DiagnosticReport(**values)


def test_card_safe_report_redacts_paths_and_route_ids(tmp_path):
    report = _report(tmp_path)

    payload = report.to_dict(card_safe=True)
    serialized = json.dumps(payload, ensure_ascii=False)

    assert "oc_secret_chat" not in serialized
    assert "ou_secret_operator" not in serialized
    assert str(tmp_path) not in serialized
    assert payload["routing"]["chat_id_hash"]


def test_card_safe_report_redacts_secrets_source_text_and_raw_hashes(tmp_path):
    raw_hash = "b" * 64
    report = _report(
        tmp_path,
        config={
            "path": str(tmp_path / "private" / "config.yaml"),
            "app_secret": "secret-value",
        },
        install_state={"source_text": "private source", "current_sha256": raw_hash},
        runtime={
            "message_id": "om_private_message",
            "credential": "private-token",
            "api_key": "private-api-key",
            "password": "private-password",
            "source_hash": "c" * 64,
        },
    )

    payload = report.to_dict(card_safe=True)
    serialized = json.dumps(payload, ensure_ascii=False)

    for sensitive in (
        "secret-value",
        "private source",
        raw_hash,
        "om_private_message",
        "private-token",
        "private-api-key",
        "private-password",
        "c" * 64,
    ):
        assert sensitive not in serialized


def test_cli_report_keeps_existing_top_level_doctor_contract(tmp_path):
    payload = _report(tmp_path, status="ok").to_dict()

    assert set(("status", "config", "hermes", "streaming", "install_state")) <= payload.keys()
    assert payload["schema_version"] == "1"
    assert isinstance(payload["recommendations"], list)


def test_diagnostic_fingerprint_ignores_created_at_and_sensitive_identifiers(tmp_path):
    report = _report(tmp_path)
    changed_volatile = replace(
        report,
        created_at=999.0,
        routing={
            **report.routing,
            "chat_id": "oc_another_chat",
            "operator_open_id": "ou_another_operator",
        },
    )

    assert report.fingerprint == changed_volatile.fingerprint


def test_diagnostic_fingerprint_ignores_runtime_counters(tmp_path):
    report = _report(
        tmp_path,
        runtime={"active_sessions": 1, "metrics": {"sessions_collected": 3}},
    )
    changed_counters = replace(
        report,
        runtime={"active_sessions": 9, "metrics": {"sessions_collected": 100}},
    )

    assert report.fingerprint == changed_counters.fingerprint


def test_diagnostic_fingerprint_changes_with_recovery_and_profile_state(tmp_path):
    report = _report(
        tmp_path,
        install_state={
            "status": "installed",
            "recovery_state": "installed",
            "recovery_fingerprint": "aaaaaaaaaaaa",
        },
    )
    changed_recovery = replace(
        report,
        install_state={"status": "incomplete", "recovery_state": "owned_incomplete"},
    )
    changed_profile = replace(
        report,
        routing={**report.routing, "profile_id": "sales", "profile_exists": False},
    )
    changed_recovery_evidence = replace(
        report,
        install_state={**report.install_state, "recovery_fingerprint": "bbbbbbbbbbbb"},
    )

    assert report.fingerprint != changed_recovery.fingerprint
    assert report.fingerprint != changed_profile.fingerprint
    assert report.fingerprint != changed_recovery_evidence.fingerprint


def test_finding_defaults_are_immutable_tuples():
    first = DiagnosticFinding("first", "info", "First")
    second = DiagnosticFinding("second", "warning", "Second")

    assert first.impact == ""
    assert first.actions == ()
    assert second.actions == ()


def test_build_route_chain_exposes_ordered_profile_route_state():
    config = {
        "server": {"host": "127.0.0.1", "port": 8765},
        "profiles": {
            "work": {
                "feishu": {"app_id": "app", "app_secret": "secret"},
                "bots": {"items": {"sales": {"app_id": "app", "app_secret": "secret"}}},
            }
        },
    }

    chain = build_route_chain(
        config,
        profile_id="work",
        profile_source="env",
        event_url="http://127.0.0.1:8765/events?ignored=yes",
        route={"bot_id": "sales", "reason": "bindings.chats"},
    )

    assert list(chain) == [
        "profile_id",
        "profile_source",
        "event_endpoint",
        "profile_exists",
        "credentials_present",
        "bot_id",
        "route_reason",
    ]
    assert chain == {
        "profile_id": "work",
        "profile_source": "env",
        "event_endpoint": "http://127.0.0.1:8765/events",
        "profile_exists": True,
        "credentials_present": True,
        "bot_id": "sales",
        "route_reason": "bindings.chats",
    }


@pytest.mark.parametrize(
    ("profile_id", "profile_source", "event_url", "route", "expected_code"),
    [
        ("", "", "http://127.0.0.1:8765/events", None, "profile_identity_missing"),
        ("ghost", "env", "http://127.0.0.1:8765/events", None, "profile_unknown"),
        ("work", "env", "http://127.0.0.1:9999/events", None, "event_endpoint_mismatch"),
        ("empty", "env", "http://127.0.0.1:8765/events", None, "profile_credentials_missing"),
        (
            "work",
            "env",
            "http://127.0.0.1:8765/events",
            {"bot_id": "ghost", "reason": "bindings.chats"},
            "bot_unknown",
        ),
        (
            "work",
            "fallback_default",
            "http://127.0.0.1:8765/events",
            {"bot_id": "sales", "reason": "bindings.fallback_bot"},
            "route_fallback",
        ),
    ],
)
def test_build_report_emits_profile_route_findings(
    tmp_path,
    profile_id,
    profile_source,
    event_url,
    route,
    expected_code,
):
    config = {
        "server": {"host": "127.0.0.1", "port": 8765},
        "feishu": {"app_id": "", "app_secret": ""},
        "profiles": {
            "work": {
                "feishu": {"app_id": "app", "app_secret": "secret"},
                "bots": {
                    "default": "sales",
                    "items": {
                        "sales": {"app_id": "app", "app_secret": "secret"},
                    },
                },
            },
            "empty": {
                "feishu": {"app_id": "", "app_secret": ""},
                "bots": {"items": {}},
            },
        },
    }
    health = {"routing": {"last_route": route or {}}}

    report = build_diagnostic_report(
        tmp_path / "config.yaml",
        config,
        _detection(tmp_path),
        _recovery_plan(tmp_path),
        health=health,
        profile_id=profile_id,
        profile_source=profile_source,
        event_url=event_url,
    )

    assert expected_code in {finding.code for finding in report.findings}
