import asyncio
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from hermes_feishu_card import hook_runtime


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "hermes_v2026_4_23"


class Message:
    chat_id = "oc_fixture"
    message_id = "msg_fixture"
    text = "fixture answer"


class Hooks:
    def __init__(self):
        self.events = []

    def emit(self, name, data):
        self.events.append((name, data))


def copy_hermes(tmp_path):
    hermes_dir = tmp_path / "hermes"
    shutil.copytree(FIXTURE, hermes_dir)
    return hermes_dir


def run_cli(*args):
    env = dict(os.environ)
    return subprocess.run(
        [sys.executable, "-m", "hermes_feishu_card.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def load_run_py(path):
    spec = importlib.util.spec_from_file_location("fixture_run", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


async def wait_for_event_count(received, expected_count, event, timeout=1):
    if len(received) >= expected_count:
        return
    await asyncio.wait_for(event.wait(), timeout=timeout)
    assert len(received) >= expected_count


async def test_installed_hook_preserves_handler_return_when_sender_fails(
    tmp_path, monkeypatch
):
    hermes_dir = copy_hermes(tmp_path)
    sender_called = asyncio.Event()

    async def failing_post_json(url, payload, timeout):
        sender_called.set()
        raise RuntimeError("sidecar down")

    monkeypatch.setattr(hook_runtime, "_post_json", failing_post_json)
    monkeypatch.setenv("HERMES_FEISHU_CARD_EVENT_URL", "http://sidecar.test/events")

    install = run_cli("install", "--hermes-dir", str(hermes_dir), "--yes")
    assert install.returncode == 0, install.stderr
    module = load_run_py(hermes_dir / "gateway" / "run.py")
    hooks = Hooks()

    result = await module._handle_message_with_agent(Message(), hooks)

    assert result == "fixture answer"
    await asyncio.wait_for(sender_called.wait(), timeout=1)
    assert len(hooks.events) == 1
    assert hooks.events[0][0] == "agent:end"
    assert hooks.events[0][1]["message"].chat_id == "oc_fixture"


async def test_installed_hook_posts_started_event_to_mock_sidecar(tmp_path, monkeypatch):
    received = []
    received_event = asyncio.Event()

    async def events(request):
        received.append(await request.json())
        received_event.set()
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/events", events)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        hermes_dir = copy_hermes(tmp_path)
        monkeypatch.setenv(
            "HERMES_FEISHU_CARD_EVENT_URL",
            str(client.make_url("/events")),
        )
        install = run_cli("install", "--hermes-dir", str(hermes_dir), "--yes")
        assert install.returncode == 0, install.stderr
        module = load_run_py(hermes_dir / "gateway" / "run.py")

        result = await module._handle_message_with_agent(Message(), Hooks())

        assert result in (None, "fixture answer")
        await asyncio.wait_for(received_event.wait(), timeout=1)
        assert received
        assert received[0]["event"] == "message.started"
        assert received[0]["chat_id"] == "oc_fixture"
        assert received[0]["message_id"] == "msg_fixture"
    finally:
        await client.close()


async def test_installed_hook_forwards_streaming_tool_and_completion_events(
    tmp_path, monkeypatch
):
    received = []
    received_count = asyncio.Event()

    async def events(request):
        received.append(await request.json())
        if len(received) >= 5:
            received_count.set()
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/events", events)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        hermes_dir = copy_hermes(tmp_path)
        monkeypatch.setenv(
            "HERMES_FEISHU_CARD_EVENT_URL",
            str(client.make_url("/events")),
        )
        hook_runtime.reset_runtime_state()
        install = run_cli("install", "--hermes-dir", str(hermes_dir), "--yes")
        assert install.returncode == 0, install.stderr
        module = load_run_py(hermes_dir / "gateway" / "run.py")

        result = await module._handle_message_with_agent(Message(), Hooks())

        assert result in (None, "fixture answer")
        await wait_for_event_count(received, 5, received_count)
        assert [item["event"] for item in received] == [
            "message.started",
            "thinking.delta",
            "tool.updated",
            "answer.delta",
            "message.completed",
        ]
        assert {item["chat_id"] for item in received} == {"oc_fixture"}
        assert {item["message_id"] for item in received} == {"msg_fixture"}
        assert received[1]["data"] == {
            "profile_id": "default",
            "profile_source": "fallback_default",
            "text": "thinking fixture delta",
            "mode": "append_block",
        }
        assert received[2]["data"] == {
            "profile_id": "default",
            "profile_source": "fallback_default",
            "tool_id": "fixture_tool",
            "name": "fixture_tool",
            "status": "running",
            "detail": "fixture tool preview",
            "arguments": {"query": "fixture"},
        }
        assert received[3]["data"] == {
            "profile_id": "default",
            "profile_source": "fallback_default",
            "text": "answer fixture delta",
        }
        assert received[4]["data"] == {
            "profile_id": "default",
            "profile_source": "fallback_default",
            "answer": "fixture answer",
            "duration": 0.25,
            "model": "Unknown",
            "tokens": {"input_tokens": 7, "output_tokens": 11},
            "context": {"used_tokens": 0, "max_tokens": 0},
            "attachments": [],
            "native_delivery": "allowed",
        }
    finally:
        await client.close()


class _CallbackCard:
    def __init__(self):
        self.type = None
        self.data = None


class _CallbackResponse:
    def __init__(self):
        self.card = None


def _card_action_data(action, *, open_id="ou_operator"):
    return SimpleNamespace(
        event=SimpleNamespace(
            action=SimpleNamespace(value=action),
            context=SimpleNamespace(open_chat_id="oc_group"),
            operator=SimpleNamespace(open_id=open_id, user_id="user-1"),
        )
    )


def _installed_action_adapter(*, allowed=True):
    class Adapter:
        name = "feishu"

        def __init__(self):
            self.allowed = []
            self.native_actions = []
            self.gray_messages = []

        def _allow_group_message(self, sender_id, chat_id, is_bot=False):
            self.allowed.append((sender_id.open_id, chat_id, is_bot))
            return allowed

        def _on_card_action_trigger(self, data):
            self.native_actions.append(data)
            return "native-fallback"

        async def _handle_card_action_event(self, data):
            self.gray_messages.append(data)

    Adapter.__module__ = hook_runtime.__name__
    adapter = Adapter()
    runner = SimpleNamespace(adapters={"feishu": adapter})
    assert hook_runtime.install_feishu_command_card_adapter_methods(runner) is True
    return adapter


@pytest.mark.parametrize(
    "operation_action",
    [
        "details",
        "recheck",
        "repair",
        "confirm_repair",
        "cancel",
        "restart",
        "confirm_restart",
        "dismiss",
    ],
)
def test_installed_ws_operations_actions_all_require_admission(
    monkeypatch, operation_action
):
    monkeypatch.setattr(hook_runtime, "CallBackCard", _CallbackCard, raising=False)
    monkeypatch.setattr(
        hook_runtime, "P2CardActionTriggerResponse", _CallbackResponse, raising=False
    )
    monkeypatch.setattr(
        hook_runtime,
        "load_runtime_config",
        lambda: SimpleNamespace(event_url="http://127.0.0.1:8765/events"),
    )
    posted = []
    monkeypatch.setattr(
        hook_runtime,
        "_post_json_sync_response",
        lambda url, payload, timeout: posted.append((url, payload, timeout))
        or {"ok": True, "card": {"schema": "2.0"}},
    )
    adapter = _installed_action_adapter()

    response = adapter._on_card_action_trigger(
        _card_action_data(
            {
                "hfc_action": "operations.select",
                "operation_action": operation_action,
                "token": "opaque-token",
                "profile_scope": "opaque-scope",
            }
        )
    )

    assert adapter.allowed == [("ou_operator", "oc_group", False)]
    assert adapter.native_actions == []
    assert posted[0][1]["event"]["action"]["value"]["operation_action"] == operation_action
    assert response.card.type == "raw"


@pytest.mark.parametrize(
    ("allowed", "open_id"),
    [(False, "ou_denied"), (True, "")],
)
def test_installed_ws_rejected_operations_are_claimed_without_gray_fallback(
    monkeypatch, allowed, open_id
):
    monkeypatch.setattr(
        hook_runtime, "P2CardActionTriggerResponse", _CallbackResponse, raising=False
    )
    monkeypatch.setattr(
        hook_runtime,
        "_post_json_sync_response",
        lambda *args: pytest.fail("rejected operation must not be forwarded"),
    )
    adapter = _installed_action_adapter(allowed=allowed)

    response = adapter._on_card_action_trigger(
        _card_action_data(
            {
                "hfc_action": "operations.select",
                "operation_action": "repair",
                "token": "opaque-token",
            },
            open_id=open_id,
        )
    )

    assert adapter.native_actions == []
    assert response.card is None


async def test_installed_ws_background_operations_suppress_native_gray_message():
    adapter = _installed_action_adapter()

    await adapter._handle_card_action_event(
        _card_action_data(
            {
                "hfc_action": "operations.select",
                "operation_action": "repair",
                "token": "opaque-token",
            }
        )
    )

    assert adapter.gray_messages == []


def test_installed_ws_unknown_action_keeps_native_fallback():
    adapter = _installed_action_adapter()
    data = _card_action_data({"hfc_action": "future.namespace"})

    response = adapter._on_card_action_trigger(data)

    assert response == "native-fallback"
    assert adapter.native_actions == [data]


def test_installed_ws_interaction_select_behavior_is_unchanged(monkeypatch):
    monkeypatch.setattr(hook_runtime, "CallBackCard", _CallbackCard, raising=False)
    monkeypatch.setattr(
        hook_runtime, "P2CardActionTriggerResponse", _CallbackResponse, raising=False
    )
    monkeypatch.setattr(
        hook_runtime,
        "load_runtime_config",
        lambda: SimpleNamespace(event_url="http://127.0.0.1:8765/events"),
    )
    posted = []
    monkeypatch.setattr(
        hook_runtime,
        "_post_json_sync_response",
        lambda url, payload, timeout: posted.append(payload)
        or {"ok": True, "card": {"schema": "2.0"}},
    )
    adapter = _installed_action_adapter(allowed=False)

    response = adapter._on_card_action_trigger(
        _card_action_data(
            {
                "hfc_action": "interaction.select",
                "interaction_id": "interaction-1",
                "choice": "approve",
                "choice_label": "Approve",
                "token": "interaction-token",
            }
        )
    )

    assert adapter.allowed == []
    assert adapter.native_actions == []
    assert posted[0]["event"]["action"]["value"]["hfc_action"] == "interaction.select"
    assert response.card.type == "raw"
