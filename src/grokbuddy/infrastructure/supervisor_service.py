"""Process-lifetime host for the bounded Phase 6 Supervisor loop."""

from __future__ import annotations

import logging
import threading
import time


class SupervisorService:
    """Run ``Supervisor.run_forever`` in one owned thread and expose readiness."""

    def __init__(self, supervisor, *, interval_seconds=5, logger=None):
        if not 0 < interval_seconds <= 5:
            raise ValueError('interval_seconds must be between 0 and 5')
        self.supervisor = supervisor
        self.interval_seconds = interval_seconds
        self.logger = logger or logging.getLogger('grokbuddy.supervisor')
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self._cycles = 0
        self._last_cycle_at = None
        self._worker_errors = {}
        self._fatal_error_code = None

    def _on_cycle(self, result):
        errors = {
            name: value['error']
            for name, value in result.items()
            if isinstance(value, dict) and isinstance(value.get('error'), str)
        }
        with self._lock:
            self._cycles += 1
            self._last_cycle_at = time.monotonic()
            self._worker_errors = errors
        if errors:
            self.logger.error(
                'GROKBUDDY_SUPERVISOR_WORKER_ERROR workers=%s',
                ','.join(f'{name}:{code}' for name, code in sorted(errors.items())),
            )

    def _run(self):
        worker_names = ','.join(self.supervisor.metrics)
        self.logger.info(
            'GROKBUDDY_SUPERVISOR_STARTED interval_seconds=%s workers=%s',
            self.interval_seconds,
            worker_names,
        )
        try:
            self.supervisor.run_forever(
                self._stop,
                interval_seconds=self.interval_seconds,
                on_cycle=self._on_cycle,
            )
            if not self._stop.is_set():
                with self._lock:
                    self._fatal_error_code = 'SUPERVISOR_STOPPED_UNEXPECTEDLY'
                self.logger.error(
                    'GROKBUDDY_SUPERVISOR_FAILED code=SUPERVISOR_STOPPED_UNEXPECTEDLY'
                )
        except BaseException as exc:  # keep readiness fail-closed even for fatal thread exits
            code = getattr(exc, 'code', type(exc).__name__)
            with self._lock:
                self._fatal_error_code = str(code)
            self.logger.exception('GROKBUDDY_SUPERVISOR_FAILED code=%s', code)
        finally:
            self.logger.info('GROKBUDDY_SUPERVISOR_STOPPED')

    def start(self):
        if self._thread is not None:
            raise RuntimeError('Supervisor service has already been started')
        self._thread = threading.Thread(
            target=self._run,
            name='grokbuddy-supervisor',
            daemon=False,
        )
        self._thread.start()

    def stop(self, timeout_seconds=None):
        if self._thread is None:
            return
        self._stop.set()
        timeout = timeout_seconds if timeout_seconds is not None else self.interval_seconds + 2
        self._thread.join(timeout)
        if self._thread.is_alive():
            with self._lock:
                self._fatal_error_code = 'SUPERVISOR_STOP_TIMEOUT'
            self.logger.error('GROKBUDDY_SUPERVISOR_FAILED code=SUPERVISOR_STOP_TIMEOUT')

    def is_ready(self):
        with self._lock:
            maximum_age = max(1, self.interval_seconds * 3)
            fresh_cycle = (
                self._last_cycle_at is not None
                and time.monotonic() - self._last_cycle_at <= maximum_age
            )
            healthy_cycle = self._cycles > 0 and fresh_cycle and not self._worker_errors
            fatal = self._fatal_error_code
        return bool(
            self._thread is not None
            and self._thread.is_alive()
            and healthy_cycle
            and fatal is None
        )

    def status(self):
        with self._lock:
            return {
                'running': bool(self._thread is not None and self._thread.is_alive()),
                'cycles': self._cycles,
                'last_cycle_recorded': self._last_cycle_at is not None,
                'worker_errors': dict(self._worker_errors),
                'fatal_error_code': self._fatal_error_code,
            }
