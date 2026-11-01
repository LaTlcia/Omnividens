"""GUI composition, reception and lifecycle; imported only for graphical modes."""
from __future__ import annotations
from queue import Empty, SimpleQueue
from threading import Event, Thread
from typing import Callable
from lilyrex.domain.events import ReplayOptions
from lilyrex.domain.ports import ControlPort, EventSource
from lilyrex.domain.replay_timeline import schedule
from lilyrex.services.battle_session import BattleSession
from lilyrex.services.controls import ViewingControls
from lilyrex.services.playback import PlaybackController
from lilyrex.services.timeline import TimelineService


def run_gui(source: EventSource, config, resources, new_session: Callable[[], BattleSession],
            controls: ControlPort, *, options: ReplayOptions | None = None,
            hold: bool = True) -> dict:
    import tkinter as tk
    from lilyrex.infra.clocks import SystemClock
    from lilyrex.infra.storage.timeline_store import TemporaryTimelineStore
    from lilyrex.ui.window import GameStyleGUI
    from lilyrex.logging_setup import get_logger
    logger = get_logger()
    logger.setLevel(config.log_level)
    store = TemporaryTimelineStore()
    timeline = TimelineService(store)
    stop = Event()
    failures: SimpleQueue = SimpleQueue()
    worker = root = None
    renders, failure = 0, None

    def produce():
        try:
            timing = options.timing if options else 'server'
            for item in schedule(source.events(), ReplayOptions(timing=timing)):
                if stop.is_set():
                    break
                timeline.append(item.event, item.timeline_seconds)
        except Exception as exc:
            failures.put(exc)
        finally:
            try:
                source.close()
            except Exception as exc:
                failures.put(exc)
            finally:
                timeline.finish()

    try:
        playback = PlaybackController(timeline, new_session, options, SystemClock())
        gate = ViewingControls(controls, lambda: playback.controls_enabled)
        root = tk.Tk()
        gui = GameStyleGUI(root, playback.view_session, resources, gate,
                           room_id=config.connection.room_id,
                           hover_delay_ms=config.preview.hover_delay_ms,
                           watcher_user_id=config.identity.watcher_user_id,
                           preview_enabled=config.preview.enabled, playback=playback)
        root.title(config.ui_title + (' · 离线回放' if options else ''))

        def poll():
            nonlocal renders, failure
            try:
                try:
                    failure = failures.get_nowait()
                except Empty:
                    pass
                if failure is not None:
                    root.quit()
                    return
                playback.advance()
                if gui.session is not playback.view_session:
                    gui.bind_session(playback.view_session)
                revision = gui._last_revision
                gui.refresh()
                renders += gui._last_revision != revision
                status = playback.status()
                if options and not hold and status.at_end and not status.paused:
                    root.quit()
                    return
                root.after(10, poll)
            except Exception as exc:
                failure = exc
                root.quit()

        worker = Thread(target=produce, daemon=True, name='battle-history-source')
        worker.start()
        root.after(0, poll)
        root.protocol('WM_DELETE_WINDOW', root.quit)
        if options and options.run_seconds is not None:
            root.after(max(1, int(options.run_seconds * 1000)), root.quit)
        root.mainloop()
    finally:
        stop.set()
        def remember_worker_failure():
            nonlocal failure
            try:
                error = failures.get_nowait()
            except Empty:
                return
            if failure is None:
                failure = error

        def release(action):
            nonlocal failure
            try:
                action()
            except Exception as exc:
                if failure is None:
                    failure = exc

        # A pending exception from setup/mainloop propagates after this finally;
        # cleanup failures must neither replace it nor skip later releases.
        remember_worker_failure()
        release(source.close)
        release(controls.stop_all)
        if worker is not None:
            release(lambda: worker.join(timeout=5))
        remember_worker_failure()
        if root is not None:
            release(root.destroy)
        if worker is not None and worker.is_alive():
            # Never close a SQLite connection while its owner is writing.
            def cleanup():
                try:
                    worker.join()
                    store.close()
                except Exception:
                    logger.error('后台回看缓存清理失败')
            if failure is None:
                failure = RuntimeError('接收线程停止超时')
            release(lambda: Thread(target=cleanup, daemon=True, name='history-cleanup').start())
        else:
            release(store.close)
    if failure is not None:
        raise failure
    status = playback.status()
    return {'events': playback.consumed_events, 'warmup_events': playback.warmup_events,
            'completed': status.at_end, 'cached_events': timeline.latest,
            'consumed_events': playback.consumed_events, 'renders': renders}
