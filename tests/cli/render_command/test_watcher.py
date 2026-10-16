import pathlib
import queue
import threading
import time
from unittest.mock import MagicMock, patch

import pytest
import typer
import watchdog.events
import watchdog.observers

from rendercv.cli.render_command import watcher
from rendercv.cli.render_command.watcher import EventHandler


class TestRunFunctionIfFilesChange:
    def test_runs_function_immediately_on_start(self, tmp_path):
        file_path = tmp_path / "test.yaml"
        file_path.touch()
        mock_function = MagicMock()

        mock_observer_class = MagicMock()
        # First join() raises KeyboardInterrupt; second join() (after stop) succeeds:
        mock_observer_class.return_value.join.side_effect = [KeyboardInterrupt, None]
        with patch.object(watcher.watchdog.observers, "Observer", mock_observer_class):
            watcher.run_function_if_files_change([file_path], mock_function)

        mock_function.assert_called_once()

    def test_reruns_function_when_file_is_modified(self, tmp_path):
        watched_file = tmp_path / "test.yaml"
        watched_file.write_text("initial", encoding="utf-8")

        call_count = 0

        def tracked_function():
            nonlocal call_count
            call_count += 1

        watcher_thread = threading.Thread(
            target=watcher.run_function_if_files_change,
            args=([watched_file], tracked_function),
            daemon=True,
        )
        watcher_thread.start()

        time.sleep(0.2)
        initial_count = call_count

        watched_file.write_text("first edit", encoding="utf-8")
        time.sleep(0.2)

        assert call_count > initial_count

    def test_reruns_function_when_secondary_file_is_modified(self, tmp_path):
        main_file = tmp_path / "cv.yaml"
        main_file.write_text("main content", encoding="utf-8")
        design_file = tmp_path / "design.yaml"
        design_file.write_text("initial design", encoding="utf-8")

        call_count = 0

        def tracked_function():
            nonlocal call_count
            call_count += 1

        watcher_thread = threading.Thread(
            target=watcher.run_function_if_files_change,
            args=([main_file, design_file], tracked_function),
            daemon=True,
        )
        watcher_thread.start()

        time.sleep(0.2)
        count_before_edit = call_count

        # Edit the design file (not the main file)
        design_file.write_text("updated design", encoding="utf-8")
        time.sleep(0.2)

        assert call_count > count_before_edit

    def test_continues_watching_after_typer_exit(self, tmp_path):
        watched_file = tmp_path / "test.yaml"
        watched_file.write_text("initial", encoding="utf-8")

        call_count = 0
        should_raise = False

        def tracked_function():
            nonlocal call_count
            call_count += 1
            if should_raise:
                raise typer.Exit(code=1)

        watcher_thread = threading.Thread(
            target=watcher.run_function_if_files_change,
            args=([watched_file], tracked_function),
            daemon=True,
        )
        watcher_thread.start()

        time.sleep(0.2)
        should_raise = True
        count_before_exit = call_count
        watched_file.write_text("edit that raises exit", encoding="utf-8")
        time.sleep(0.2)

        assert call_count > count_before_exit

        should_raise = False
        count_after_exit = call_count
        watched_file.write_text("edit after exit", encoding="utf-8")
        time.sleep(0.2)

        assert call_count > count_after_exit


class TestEventHandler:
    def test_ignores_events_for_unwatched_files(self):
        mock_fn = MagicMock()
        handler = EventHandler(mock_fn, watched_files={"/watched/file.yaml"})

        event = watchdog.events.FileModifiedEvent("/other/file.yaml")
        handler.on_modified(event)

        mock_fn.assert_not_called()

    def test_calls_function_for_watched_file(self):
        mock_fn = MagicMock()
        handler = EventHandler(mock_fn, watched_files={"/watched/file.yaml"})

        event = watchdog.events.FileModifiedEvent("/watched/file.yaml")
        handler.on_modified(event)

        mock_fn.assert_called_once()

    def test_suppresses_typer_exit(self):
        mock_fn = MagicMock(side_effect=typer.Exit(code=1))
        handler = EventHandler(mock_fn, watched_files={"/watched/file.yaml"})

        event = watchdog.events.FileModifiedEvent("/watched/file.yaml")
        handler.on_modified(event)

        mock_fn.assert_called_once()


@pytest.mark.parametrize(
    "event",
    [
        watchdog.events.FileCreatedEvent("/watched/file.yaml"),
        watchdog.events.FileDeletedEvent("/watched/file.yaml"),
        watchdog.events.FileMovedEvent("/watched/temporary", "/watched/file.yaml"),
        watchdog.events.FileMovedEvent("/watched/file.yaml", "/watched/backup"),
        watchdog.events.DirCreatedEvent("/watched"),
        watchdog.events.DirMovedEvent("/temporary", "/watched"),
    ],
)
def test_replacement_and_creation_events_trigger_render(event):
    callback = MagicMock()
    handler = EventHandler(callback, {"/watched/file.yaml"})
    handler.dispatch(event)
    callback.assert_called_once()


@pytest.mark.parametrize(
    "event",
    [
        watchdog.events.DirModifiedEvent("/watched"),
        watchdog.events.FileOpenedEvent("/watched/file.yaml"),
        watchdog.events.FileClosedNoWriteEvent("/watched/file.yaml"),
        watchdog.events.FileCreatedEvent("/watched/output.pdf"),
        watchdog.events.DirCreatedEvent("/watched-other"),
    ],
)
def test_read_and_unrelated_events_do_not_trigger_render(event):
    callback = MagicMock()
    handler = EventHandler(callback, {"/watched/file.yaml"})
    handler.dispatch(event)
    callback.assert_not_called()


def test_watch_updates_directories_and_recovers_after_replacement_and_creation(
    tmp_path, monkeypatch
):
    selection = tmp_path / "selection.txt"
    first = tmp_path / "first" / "design.yaml"
    second = tmp_path / "second" / "design.yaml"
    future = tmp_path / "future" / "nested" / "design.yaml"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    selection.write_text(str(first), encoding="utf-8")
    observed = queue.Queue()
    missing = threading.Event()
    observer = watchdog.observers.Observer()
    monkeypatch.setattr(watcher.watchdog.observers, "Observer", lambda: observer)

    def paths():
        return [selection, pathlib.Path(selection.read_text(encoding="utf-8"))]

    def render():
        try:
            observed.put(paths()[1].read_text(encoding="utf-8"))
        except FileNotFoundError:
            missing.set()
            raise typer.Exit(code=1) from None

    def expect(text):
        deadline = time.monotonic() + 5
        while True:
            assert time.monotonic() < deadline, f"No render containing {text!r}"
            if observed.get(timeout=max(0.01, deadline - time.monotonic())) == text:
                return

    thread = threading.Thread(
        target=watcher.run_function_if_files_change, args=(paths, render), daemon=True
    )
    thread.start()
    try:
        expect("first")
        # Editors commonly save by renaming a temporary file over the original.
        replacement = tmp_path / "replacement.txt"
        replacement.write_text(str(second), encoding="utf-8")
        replacement.replace(selection)
        expect("second")
        second.write_text("second updated", encoding="utf-8")
        expect("second updated")
        replacement.write_text("atomic update", encoding="utf-8")
        replacement.replace(second)
        expect("atomic update")

        second.unlink()
        assert missing.wait(5)
        second.write_text("recreated", encoding="utf-8")
        expect("recreated")

        missing.clear()
        replacement.write_text(str(future), encoding="utf-8")
        replacement.replace(selection)
        assert missing.wait(5)
        future.parent.mkdir(parents=True)
        future.write_text("new directory", encoding="utf-8")
        expect("new directory")
    finally:
        observer.stop()
        thread.join(timeout=5)
    assert not thread.is_alive()
