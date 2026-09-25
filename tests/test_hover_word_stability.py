"""One answer per word under the production hover composition.

Direct text returns a word with its own screen rectangle and no ROI geometry.
Before retention used that rectangle, every pixel of movement inside the word
started a new lookup and re-rendered the popup, which is what Windows showed.
This drives the real manual/hover composition with a platform reader that
answers like UIA or AX, and counts what reaches the popup.
"""

from __future__ import annotations

from collections.abc import Callable
from threading import Event
from typing import Any

import pytest
from hanly import (
    BoundingBox,
    DictionaryEntry,
    LookupContext,
    LookupResult,
    LookupStatus,
    Point,
    TextSelection,
)
from hanly_app import manual_lookup
from hanly_app.lookup_controller import LookupController, LookupRequest, ResultDispatcher
from hanly_app.manual_lookup import create_manual_lookup
from hanly_app.text_acquisition import Acquisition, Outcome

from tests.test_hover_lookup import (
    _ALWAYS_ACTIVE,
    _await_hover_ready,
    _Capture,
    _HotkeyFactory,
    _ListenerFactory,
    _QueueDispatcher,
    _Scheduler,
)

#: Two words on one line, each 60 x 24 pixels, as a control would report them.
_WORDS = {
    "초대": BoundingBox(100, 100, 160, 124),
    "받다": BoundingBox(170, 100, 230, 124),
}


class _Reader:
    """Answers like a platform accessibility reader: the word and its bounds."""

    def __init__(self) -> None:
        self.reads = 0

    @property
    def timeout_ms(self) -> int:
        return 40

    def submit(self, point: Point, deliver: Callable[[Acquisition], None]) -> int:
        self.reads += 1
        for word, box in _WORDS.items():
            if box.left <= point.x <= box.right and box.top <= point.y <= box.bottom:
                deliver(
                    Acquisition(
                        Outcome.DIRECT,
                        selection=TextSelection(word, 0, source="accessibility"),
                        bounds=box,
                    )
                )
                return self.reads
        deliver(Acquisition(Outcome.UNSUPPORTED))
        return self.reads

    def close(self) -> None:
        return None


class _Worker:
    def __init__(self) -> None:
        self.lookups = 0

    def __call__(self, request: LookupRequest) -> LookupResult:
        self.lookups += 1
        word = request.selection.text if request.selection is not None else "?"
        return LookupResult(
            status=LookupStatus.SUCCESS,
            entries=(DictionaryEntry(headword=word, definitions=("gloss",)),),
            context=LookupContext(text=word, lemma=word),
        )

    def close(self) -> None:
        return None


def test_moving_inside_one_word_never_looks_it_up_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = _Reader()
    worker = _Worker()
    monkeypatch.setattr(manual_lookup, "default_text_acquisition", lambda: reader)
    dispatcher = _QueueDispatcher()
    listeners = _ListenerFactory()
    scheduler = _Scheduler()

    class _Composition:
        def create_lookup_controller(
            self,
            on_result: Callable[[LookupResult], None] | None = None,
            *,
            result_dispatcher: ResultDispatcher | None = None,
            thread_name: str | None = None,
        ) -> LookupController:
            del thread_name
            assert on_result is not None
            return LookupController(lambda: worker, on_result, result_dispatcher=result_dispatcher)

    presented: list[LookupResult] = []
    manual = create_manual_lookup(
        _Composition(),
        _Capture(),
        presented.append,
        close_popup=lambda: None,
        current_cursor=lambda: Point(0, 0),
        dispatcher=dispatcher,
        hotkey_factory=_HotkeyFactory(),
        hover_enabled=True,
        hover_delay_ms=120,
        hover_scheduler=scheduler,
        hover_listener_factory=listeners,
        app_config=_ALWAYS_ACTIVE,
    )

    def hover(x: int, y: int, expect_popup: bool) -> None:
        before = len(presented)
        listeners.listeners[-1].emit(x, y)
        _drain(dispatcher)
        if scheduler.calls:
            scheduler.fire()
            scheduler.calls.clear()
        if expect_popup:
            assert dispatcher.drain_until(lambda: len(presented) > before)
        _drain(dispatcher)

    def settle_moves(points: list[tuple[int, int]]) -> None:
        for x, y in points:
            hover(x, y, expect_popup=False)

    manual.start()
    try:
        runtime = manual.hover_runtime
        assert runtime is not None
        _await_hover_ready(runtime, dispatcher)

        hover(110, 110, expect_popup=True)
        assert [result.entries[0].headword for result in presented] == ["초대"]

        # A few pixels at a time, across the whole word and its 4px margin.
        settle_moves([(112, 111), (130, 108), (150, 118), (158, 104), (99, 112), (163, 110)])
        assert len(presented) == 1, "moving inside the word re-rendered the popup"
        assert worker.lookups == 1

        hover(180, 110, expect_popup=True)
        assert [result.entries[0].headword for result in presented] == ["초대", "받다"]
        settle_moves([(190, 112), (200, 108), (225, 118)])
        assert len(presented) == 2
        assert worker.lookups == 2
    finally:
        manual.shutdown()


def _drain(dispatcher: _QueueDispatcher) -> None:
    for _ in range(50):
        if not dispatcher.pending:
            Event().wait(0.01)
            if not dispatcher.pending:
                return
        dispatcher.drain_one()


def _unused(*_args: Any) -> None:
    return None
