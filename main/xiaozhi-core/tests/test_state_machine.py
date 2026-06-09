"""显式状态机：转移与打断。"""

import asyncio

from xiaozhi_core import DialogueState, DialogueStateMachine, EventBus, SessionContext
from xiaozhi_core.domain.events import Event, TurnAborted, TurnCompleted, TurnStarted


def _collect(bus: EventBus) -> list[Event]:
    events: list[Event] = []
    bus.subscribe(Event, events.append)
    return events


def test_full_turn_transitions():
    async def run():
        bus = EventBus()
        session = SessionContext()
        sm = DialogueStateMachine(bus, session)
        events = _collect(bus)

        await sm.on_voice_started()
        assert sm.state is DialogueState.LISTENING
        turn = await sm.on_voice_stopped()
        assert sm.state is DialogueState.RECOGNIZING and turn is not None
        await sm.on_asr_finalized()
        assert sm.state is DialogueState.THINKING
        await sm.on_speaking()
        assert sm.state is DialogueState.SPEAKING
        turn.user_text = "问"
        turn.assistant_text = "答"
        await sm.on_finished()
        assert sm.state is DialogueState.IDLE
        assert session.current_turn is None

        assert any(isinstance(e, TurnStarted) for e in events)
        completed = [e for e in events if isinstance(e, TurnCompleted)]
        assert completed and completed[0].assistant_text == "答"

    asyncio.run(run())


def test_abort_from_any_state():
    async def run():
        bus = EventBus()
        session = SessionContext()
        sm = DialogueStateMachine(bus, session)
        events = _collect(bus)

        await sm.on_voice_stopped()
        turn = session.current_turn
        assert turn is not None
        await sm.abort()
        assert sm.state is DialogueState.IDLE
        assert turn.aborted
        assert session.current_turn is None
        assert any(isinstance(e, TurnAborted) for e in events)

    asyncio.run(run())


def test_invalid_transition_is_lenient():
    async def run():
        bus = EventBus()
        sm = DialogueStateMachine(bus, SessionContext())
        await sm.on_asr_finalized()  # IDLE 下直接 asr_finalized：忽略不抛
        assert sm.state is DialogueState.IDLE

    asyncio.run(run())
