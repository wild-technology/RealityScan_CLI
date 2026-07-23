#!/usr/bin/env python3
from __future__ import annotations

import abc
import logging
import sys
import time
from tqdm import tqdm

from module_base.parameter import Parameter

class RSModule(abc.ABC):
    """
    Base class for all ROV-processing modules.
    """

    params: dict[str, Parameter] = None
    loading_bars: list[tqdm] = None
    logger: logging.Logger

    def __init__(self, name: str, logger: logging.Logger):
        self._name = name
        self.logger = logger
        self.params = {}
        self.loading_bars = []

    @property
    def name(self) -> str:
        return self._name

    def get_name(self) -> str:
        return self._name

    def set_params(self, all_params: dict[str, Parameter]) -> None:
        """
        Injects the global Parameter dict so this module can pick out its own.
        """
        self.params = all_params

    def get_parameters(self) -> dict[str, Parameter]:
        """
        Default: no parameters. Subclasses should override if they need any.
        """
        return {}

    @abc.abstractmethod
    def run(self) -> dict[str, object] | None:
        """
        Execute the module’s main logic.
        """
        ...

    def finish(self) -> None:
        """
        Optional hook after run() completes; closes any open loading bars.
        """
        for bar in self.loading_bars:
            bar.close()
        time.sleep(0.2)

    def validate_parameters(self) -> tuple[bool, str | None]:
        """
        Default parameter validation (override if needed).
        """
        return True, None

    def _initialize_loading_bar(self, total: int, description: str) -> tqdm:
        bar = tqdm(
            total=total,
            unit="steps",
            desc=description,
            leave=True,
            miniters=1,
            file=sys.stdout,
        )
        self.loading_bars.append(bar)
        return bar

    def _update_loading_bar(self, bar: tqdm, increment: int = 1) -> None:
        bar.n = min(bar.n + increment, bar.total)
        bar.refresh()

    def _finish_loading_bar(self, bar: tqdm) -> None:
        bar.n = bar.total
        bar.refresh()

    def get_progress(self) -> float:
        # bars created with total=0 (nothing to do) count as complete
        bars = [bar for bar in self.loading_bars if bar.total]
        if not bars:
            return 1.0 if self.loading_bars else 0.0
        return sum(bar.n / bar.total for bar in bars) / len(bars)
