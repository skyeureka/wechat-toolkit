"""M2 KeyCaptureService: shared capture-to-keystore orchestration (CLI + Web UI).

Reuses the Frida agent internals from keyagent. The caller is responsible for making
sure WeChat is fully closed before invoking (Web UI asks first).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..config import ERR_LOGIN_TIMEOUT, ERR_NO_WEIXIN, ERR_UNSUPPORTED_VERSION, KeyagentError
from ..keyagent import keystore, version_map, wechat_state
from ..keyagent.account import Account
from ..keyagent.agent import capture_key
from ..keyagent.locate_anchors import LocateError, locate_anchors
from ..keyagent.verify import test_key_against_db
from ..models import AnchorSet
from ..models import KeyInfo

ProgressCallback = Callable[[str, object], None]  # stage -> payload


class CaptureService:
    @staticmethod
    def find_weixin_exe(explicit: str | None) -> Path:
        if explicit:
            return Path(explicit)
        exe = wechat_state.find_weixin_exe()
        if exe is None:
            raise KeyagentError(ERR_NO_WEIXIN, "Weixin.exe not found; pass --weixin-exe explicitly")
        return exe

    @classmethod
    def anchor_candidates(cls, exe: Path) -> list[AnchorSet]:
        """Anchor sets to try, best guess first.

        An install root can hold several version dirs (e.g. 4.1.13.12 and 4.1.15.12).
        The launcher loads the newest DLL, so try that first; if its hooks never fire,
        fall back to the other registered versions rather than failing outright.
        """
        versions = wechat_state.installed_wechat_versions()   # newest DLL first
        out: list[AnchorSet] = []
        for ver, dll in versions:
            if dll.name != "Weixin.dll":
                continue
            anchors = version_map.resolve_anchors(ver)
            if anchors and anchors not in out:
                out.append(anchors)
        if out:
            return out
        # nothing registered: locate on the spot
        for dll in (exe.with_name("Weixin.dll"), exe.parent.parent / "Weixin.dll"):
            if dll.exists():
                try:
                    anchors = locate_anchors(dll)
                    version_map.save_anchor_cache([anchors])
                    return [anchors]
                except LocateError:
                    continue
        raise KeyagentError(
            ERR_UNSUPPORTED_VERSION,
            "no registered anchors for installed WeChat version; run `keyagent locate`",
        )

    @classmethod
    def resolve_anchors(cls, exe: Path) -> AnchorSet:
        return cls.anchor_candidates(exe)[0]

    @classmethod
    def run(
        cls,
        account: Account,
        weixin_exe: str | None = None,
        observe_ms: int = 120_000,
        store: bool = True,
        progress: ProgressCallback | None = None,
    ) -> KeyInfo:
        if wechat_state.is_weixin_running():
            raise KeyagentError(
                4,
                "WeChat is currently running. For automatic capture it must be fully closed "
                "(a normal open/sign-in then tray-exit first keeps auto-login working).",
            )
        exe = cls.find_weixin_exe(weixin_exe)
        candidates = cls.anchor_candidates(exe)

        last_error: Exception | None = None
        for attempt, anchors in enumerate(candidates, 1):
            if progress:
                progress(
                    "attempt",
                    f"{attempt}/{len(candidates)} — WeChat {anchors.wechat_version} "
                    f"(entry=0x{anchors.entry:X})",
                )
            try:
                outcome = capture_key(
                    exe,
                    anchors,
                    account.message_db,
                    account_id=account.account_id,
                    observe_ms=observe_ms,
                    progress=progress,
                )
            except KeyagentError as exc:
                last_error = exc
                # Hooks that never fired mean the anchors did not match the loaded DLL;
                # a login/cleanup failure would repeat on every candidate.
                if exc.code == ERR_LOGIN_TIMEOUT and attempt < len(candidates):
                    if progress:
                        progress("retry", f"no codec activity with {anchors.wechat_version}; next")
                    continue
                raise
            key = outcome.key
            if key is None:
                raise KeyagentError(4, "capture finished without a validated key")
            ok, detail = test_key_against_db(key.password, account.message_db)
            if not ok:
                raise KeyagentError(4, f"captured key failed DB validation: {detail}")
            if store:
                keystore.store_key(key)
                if progress:
                    progress("stored", f"fp={key.fingerprint}")
            return key
        raise last_error or KeyagentError(4, "capture failed")
