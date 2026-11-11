"""mitmdump 加载的 addon。环境变量由 recorder.recorder_process 注入。"""

from __future__ import annotations

import logging

from tapmock.recorder import record_flow, store_from_env

LOGGER = logging.getLogger("tapmock.addon")


class TapmockRecorder:
    def __init__(self) -> None:
        self.store = store_from_env()

    def response(self, flow) -> None:  # noqa: ANN001 - mitmproxy 的 flow 类型
        try:
            record_flow(self.store, flow)
        except Exception as exc:  # noqa: BLE001 - 单条录制失败不应中断整个代理
            LOGGER.warning("录制失败：%s", exc)


addons = [TapmockRecorder()]
