"""Composition root for live and offline applications."""
from __future__ import annotations
from pathlib import Path
import json
import time
from lilyrex.config import AppConfig, load_app_config, load_passive_settings
from lilyrex.domain.events import ReplayOptions


def make_session_factory(config: AppConfig, namebases: dict | None = None, catalog=None):
    from lilyrex.infra.battle_snapshot import snapshot_from_history
    from lilyrex.infra.damage_catalog import LocalDamageCatalog
    from lilyrex.infra.masterdata.repository import job_card_types, load_namebases
    from lilyrex.services.battle_session import BattleSession
    from lilyrex.services.damage_preview import DamagePreviewService
    bases = namebases or load_namebases(config.namebase_dir)
    jobs = job_card_types(bases['chara_data'])
    card_attributes = {cid: row[1] for cid, row in bases['card_data'].items()}
    catalog = catalog or LocalDamageCatalog(
        config.catalog_dir / 'damage_catalog.json' if config.catalog_dir else None)
    passives = load_passive_settings(config.path)
    def create():
        preview = DamagePreviewService(catalog, config.preview.settings_for, passives)
        return BattleSession(preview, lambda history: snapshot_from_history(history, jobs), card_attributes)
    return create


def make_session(config: AppConfig, namebases: dict | None = None):
    return make_session_factory(config, namebases)()


def replay_options(args, config: AppConfig) -> ReplayOptions:
    return ReplayOptions(timing=args.timing or config.replay_timing,
                         speed=args.speed if args.speed is not None else config.replay_speed,
                         start_seconds=args.start, run_seconds=args.seconds,
                         warmup=config.replay_warmup and not args.no_warmup)


def _print_result(value: dict, json_output: bool = True) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=None if json_output else 2))


def _bench(source, options, config):
    from lilyrex.services.replay import ReplayRunner
    session = make_session(config)
    times, previews, successful, warmup = [], 0, 0, 0
    begin = time.perf_counter()
    try:
        for item in ReplayRunner(source, options).timed_events():
            if options.run_seconds and time.perf_counter() - begin >= options.run_seconds:
                break
            started = time.perf_counter()
            session.consume(item.event, warmup=item.warmup)
            warmup += item.warmup
            if item.event.name == 'response:gvg_skill_exec_player':
                for effect in item.event.payload.get('influence', []):
                    if effect.get('effectType') == 100:
                        card, skill = effect.get('cardMstId', 0), effect.get('skillMstId', 0)
                        if session.preview.catalog.skill(card, skill):
                            previews += 1
                            result = session.preview.preview(effect['actionUserId'], card, skill)
                            successful += bool(result.estimates)
            times.append((time.perf_counter() - started) * 1000)
    finally:
        source.close()
    ordered = sorted(times)
    percentile = lambda q: ordered[min(len(ordered) - 1, int((len(ordered) - 1) * q))] if ordered else 0
    return {'events': session.event_count, 'warmup_events': warmup, 'damage_previews': previews,
            'successful_previews': successful, 'elapsed_seconds': time.perf_counter() - begin,
            'state_and_preview_ms': {'p50': percentile(.5), 'p95': percentile(.95), 'max': max(times, default=0)}}


def _gui_data(config: AppConfig, *, offline: bool = False):
    """Select one coherent immutable dataset before the viewing session starts."""
    from lilyrex.infra.damage_catalog import LocalDamageCatalog
    from lilyrex.infra.masterdata.repository import load_namebases
    from lilyrex.logging_setup import get_logger
    logger = get_logger()
    logger.setLevel(config.log_level)
    if config.namebase_dir or config.catalog_dir:
        logger.info('使用显式本地主数据目录，跳过自动更新')
        if config.namebase_dir and not config.catalog_dir:
            logger.warning('本地名称库未指定配套计算目录，使用内置计算数据')
        return load_namebases(config.namebase_dir), LocalDamageCatalog(
            config.catalog_dir / 'damage_catalog.json' if config.catalog_dir else None)
    from lilyrex.infra.masterdata.github_source import GitHubMasterdataSource
    from lilyrex.infra.masterdata.version_store import VersionStore
    from lilyrex.services.masterdata_update import refresh_masterdata
    settings = config.masterdata_update
    try:
        store = VersionStore(settings.cache_dir)
        remote = GitHubMasterdataSource(owner=settings.owner, repository=settings.repository,
            branch=settings.branch, subdirectory=settings.subdirectory)
        result = refresh_masterdata(remote, store, enabled=settings.enabled and not offline,
            check_timeout=settings.check_timeout, download_timeout=settings.download_timeout,
            total_timeout=settings.total_timeout, progress=logger.info)
        (logger.warning if result.status == 'fallback' else logger.info)(result.notice)
        if result.version is not None:
            directory = store.directory(result.version)
            bases = load_namebases(directory / 'namebases')
            catalog = LocalDamageCatalog(directory / 'damage_catalog.json')
            return bases, catalog
    except Exception:
        # Cache creation/reads can fail before the update service gets control.
        logger.warning('本机更新数据不可用，使用内置名称与计算数据')
    return load_namebases(), LocalDamageCatalog()


def _gui(source, config, *, options=None, hold=True, offline=False):
    from lilyrex.gui_runtime import run_gui
    from lilyrex.ui.view_models import UiResources
    from lilyrex.infra.masterdata.repository import assets_path
    from lilyrex.services.controls import DisabledControls
    bases, catalog = _gui_data(config, offline=offline)
    resources = UiResources(**bases, assets_path=assets_path(config.assets_dir))
    if options is None:
        from lilyrex.infra.transport.control_client import ControlPool
        controls = ControlPool(config.connection, config.identity)
    else:
        controls = DisabledControls()
    return run_gui(source, config, resources, make_session_factory(config, bases, catalog), controls,
                   options=options, hold=hold)


def run(args) -> int:
    config = load_app_config(args.config)
    if args.command == 'replay':
        from lilyrex.infra.storage.recording import RecordingSource
        if args.mode == 'import':
            from lilyrex.infra.storage.legacy_import import import_legacy
            result = import_legacy(args.recording, args.out)
        elif args.mode == 'analyze':
            from lilyrex.services.replay_analysis import analyze
            result = analyze(RecordingSource(args.recording))
        else:
            source = RecordingSource(args.recording)
            options = replay_options(args, config)
            result = (_bench(source, options, config) if args.mode == 'bench' and args.headless
                      else _gui(source, config, options=options,
                                hold=args.hold or (args.mode == 'gui' and not args.exit_at_end),
                                offline=getattr(args, 'offline', False)))
        _print_result(result, getattr(args, 'json', False))
    elif args.command == 'data':
        from lilyrex.infra.masterdata.namebases import build_namebases
        _print_result(build_namebases(args.source, args.out))
    else:
        config.require_connection()
        from lilyrex.infra.transport.socketio_client import LiveEventSource
        source = LiveEventSource(config.connection, config.identity)
        if args.command == 'record':
            from lilyrex.infra.storage.recording import RecordingWriter
            from lilyrex.services.recording import record
            _print_result(record(source, RecordingWriter(args.out), args.duration, int(args.max_mb * 1024 ** 2)))
        else:
            _print_result(_gui(source, config, offline=getattr(args, 'offline', False)))
    return 0
