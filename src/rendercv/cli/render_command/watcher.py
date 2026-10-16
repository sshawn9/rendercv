import contextlib
import os
import pathlib
import threading
from collections.abc import Callable
from typing import cast

import typer
import watchdog.events
import watchdog.observers


class EventHandler(watchdog.events.FileSystemEventHandler):
    """Re-render on edits, replacement saves, or removal of a watched input."""

    def __init__(self, function: Callable[[], None], watched_files: set[str]) -> None:
        super().__init__()
        self.function = function
        self.watched_files = watched_files

    def on_modified(self, event: watchdog.events.FileSystemEvent) -> None:
        # Directory modification events also accompany unrelated output writes.
        if event.is_directory and event.event_type == "modified":
            return
        changed_paths = {os.fsdecode(event.src_path), os.fsdecode(event.dest_path)} - {
            ""
        }
        if not any(
            path in self.watched_files
            or (
                event.is_directory
                and any(
                    pathlib.Path(file).is_relative_to(path)
                    for file in self.watched_files
                )
            )
            for path in changed_paths
        ):
            return
        with contextlib.suppress(typer.Exit):
            self.function()

    on_created = on_modified
    on_deleted = on_modified
    on_moved = on_modified


def run_function_if_files_change(
    file_paths: list[pathlib.Path] | Callable[[], list[pathlib.Path]],
    function: Callable[[], None],
) -> None:
    """Watch inputs and re-render, refreshing references after configuration edits.

    Args:
        file_paths: Files to watch, or a callback resolving the current inputs.
        function: Zero-argument callback to invoke initially and on file changes.
    """
    observer = watchdog.observers.Observer()
    scheduled = {}
    render_lock = threading.Lock()

    def refresh_watches() -> None:
        paths = (
            cast(Callable[[], list[pathlib.Path]], file_paths)()
            if callable(file_paths)
            else file_paths
        )
        event_handler.watched_files = {str(path.absolute()) for path in paths}
        directories = set()
        for path in paths:
            directory = path.absolute().parent
            # A referenced file's directory may not have been created yet.
            # Watch its nearest existing ancestor until it becomes available.
            while not directory.is_dir() and directory != directory.parent:
                directory = directory.parent
            directories.add(str(directory))
        for directory in directories - scheduled.keys():
            scheduled[directory] = observer.schedule(
                event_handler, directory, recursive=False
            )
        for directory in scheduled.keys() - directories:
            observer.unschedule(scheduled.pop(directory))

    def render_after_change() -> None:
        with render_lock:
            refresh_watches()
            function()

    event_handler = EventHandler(render_after_change, set())
    refresh_watches()
    try:
        # Serialize the initial render with event callbacks. Only the event thread
        # updates subscriptions once the observer starts, avoiding lock inversion.
        with render_lock:
            observer.start()
            with contextlib.suppress(typer.Exit):
                function()
        observer.join()
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        if observer.ident is not None:
            observer.join()
