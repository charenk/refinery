"""Socket.IO event emitter that the agents call into during a scan.

`ui/app.py` registers the Socket.IO instance on startup. If the UI server is
not running, `_socketio` stays `None` and every emit becomes a no-op, so a
scan never crashes because the dashboard is offline.

Event types emitted to the browser:

  agent_state   {agent_id, state}        State transition for one agent desk.
                                         state in {idle, active, reading,
                                         writing, done, error}.
  packet        {from_id, to_id, color}  A pixel "data packet" travels between
                                         two agent desks on the office canvas.
  runner        {from_id, to_id, color}  A small clipboard sprite walks the
                                         floor lane from one station to the
                                         other. Use sparingly: one per
                                         meaningful cross-agent handoff.
  agent_walk    {from_id, to_id,         The agent leaves their desk, walks
                 collab_ms}              to the collaborator (chair becomes
                                         empty), stands for collab_ms, then
                                         walks back. Use very sparingly.
  log           {agent_id, message}      Append a line to the office HUD log.
  scan_complete {}                       The orchestrator finished a run.
"""

import logging

logger = logging.getLogger(__name__)

_socketio = None  # set by app.py on startup


def register(socketio_instance) -> None:
    """Bind the live Socket.IO instance so subsequent emits reach the browser."""
    global _socketio
    _socketio = socketio_instance


def _safe_emit(event_name: str, payload: dict) -> None:
    if _socketio is None:
        return
    try:
        _socketio.emit(event_name, payload)
    except Exception as error:
        logger.debug("Socket emit %s failed (UI probably not running): %s", event_name, error)


def agent_state(agent_id: str, state: str) -> None:
    """Emit an agent state change. State must be one of the documented values."""
    _safe_emit("agent_state", {"agent_id": agent_id, "state": state})


def packet(from_id: str, to_id: str, color: str) -> None:
    """Emit a data packet animation from `from_id` desk to `to_id` desk."""
    _safe_emit("packet", {"from_id": from_id, "to_id": to_id, "color": color})


def runner(from_id: str, to_id: str, color: str = "#c8a050") -> None:
    """Emit a clipboard runner walking from `from_id` to `to_id`.

    Use at meaningful cross-agent handoffs (e.g., orchestrator dispatching
    work to scanner). Sprinkle sparingly: one per logical handoff, not per
    method call. The runner takes about 2.2 seconds to traverse the room.
    """
    _safe_emit("runner", {"from_id": from_id, "to_id": to_id, "color": color})


def agent_walk(from_id: str, to_id: str, collab_ms: int = 1500) -> None:
    """Emit an "agent leaves their chair and walks over" animation.

    The agent's chair becomes empty for the duration. Their desk monitor
    keeps showing the logical state. Use only at the most important
    handoffs (e.g., post-mortem agent walking to learning agent during
    the weekly review). Total animation ~5 seconds out + collab + back.
    """
    _safe_emit("agent_walk", {"from_id": from_id, "to_id": to_id, "collab_ms": collab_ms})


def log(agent_id: str, message: str) -> None:
    """Append a line to the office HUD, attributed to `agent_id`."""
    _safe_emit("log", {"agent_id": agent_id, "message": message})


def scan_complete() -> None:
    """Signal that the orchestrator finished its run."""
    _safe_emit("scan_complete", {})
