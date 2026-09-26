"""Capture the WeChat 4.x DB key on Windows, auto-clicking the account picker.

Why this exists: `chattrace keyagent run` spawns Weixin.exe with the caller's working
directory (not the install dir) and has no way to confirm the account picker. On
Windows WeChat 4.1.15.12 the spawned instance lands on the "进入微信" account-picker
window and waits, so no codec activity ever fires and capture times out.

This variant:
  * spawns with cwd = the WeChat install dir
  * arms the same three anchors
  * while observing, polls for the account-picker window (green "进入微信" button)
    and clicks it -- targeting ONLY the pid we spawned
  * HMAC-validates every candidate against the real DB page before accepting it

Usage:
    python capture_win.py <account_dir> [observe_seconds]
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import frida

from chattrace.keyagent.agent import JS_TEMPLATE, _verify_live
from chattrace.keyagent import keystore
from chattrace.keyagent.wechat_state import find_weixin_exe, installed_wechat_versions
from chattrace.keyagent.version_map import resolve_anchors
from chattrace.models import KeyInfo

CLICK_PS1 = Path(__file__).with_name("click_enter.ps1")


def run_clicker(pid: int) -> str:
    """Invoke the window clicker once; return its status token."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(CLICK_PS1), "-TargetPid", str(pid), "-Quiet"],
            capture_output=True, text=True, timeout=45,
        )
        return (r.stdout or "").strip() or f"exit{r.returncode}"
    except subprocess.TimeoutExpired:
        return "timeout"
    except Exception as exc:
        return f"err:{exc}"


def clicker_loop(pid: int, stop: threading.Event, log, on_clicked=None) -> None:
    """Click the account-picker button until the key is captured or time runs out.

    The picker is only clickable while it is actually on top; the clicker raises the
    window and verifies the click point belongs to our pid, reporting OCCLUDED when
    another window is still in the way. OCCLUDED is retried rather than treated as
    "no picker", so a window manager that is slow to raise the window cannot stall the
    capture.
    """
    attempts = 0
    clicks = 0
    while not stop.is_set():
        if stop.wait(2.0):
            break
        attempts += 1
        status = run_clicker(pid)
        if status.startswith("CLICKED"):
            clicks += 1
            log(f"[autoclick] {status} (click #{clicks})")
            if on_clicked is not None:
                on_clicked()
            # after a click the picker usually disappears; stop retrying soon after
            if clicks >= 2:
                log("[autoclick] clicked; stopping retries")
                break
            stop.wait(3.0)
        elif status.startswith("OCCLUDED"):
            if attempts <= 6:
                log(f"[autoclick] window not on top yet ({status}); retrying")
            stop.wait(0.6)
        elif status in ("NOWINDOW", "NOBUTTON") or status.startswith("exit"):
            if attempts <= 3:
                log(f"[autoclick] no picker yet ({status})")
        else:
            if attempts <= 5:
                log(f"[autoclick] {status}")


def main() -> int:
    account_dir = Path(sys.argv[1])
    observe = int(sys.argv[2]) if len(sys.argv) > 2 else 180
    auto = "--no-autoclick" not in sys.argv
    account_id = account_dir.name
    message_db = account_dir / "db_storage" / "message" / "message_0.db"
    if not message_db.exists():
        print(f"!! message_0.db not found: {message_db}")
        return 2

    exe = find_weixin_exe()
    if exe is None:
        print("!! Weixin.exe not found")
        return 2

    # Anchors must match the Weixin.dll the launcher actually loads. The install root
    # can hold several version dirs (e.g. 4.1.13.12 and 4.1.15.12); picking whichever
    # version merely happens to be registered first arms hooks at addresses that do not
    # exist in the loaded DLL, so no hook ever fires. Order candidates newest-DLL-first
    # (what the launcher uses) and retry down the list when an attempt observes nothing.
    candidates: list[tuple[str, object]] = []
    for ver, _dll in installed_wechat_versions():
        a = resolve_anchors(ver)
        if a:
            candidates.append((ver, a))
    if not candidates:
        print("!! no registered anchors - run `chattrace keyagent locate --weixin-dll <path>` first")
        return 3

    print(f"exe        = {exe}")
    print(f"account    = {account_id}")
    print(f"autoclick  = {auto}")
    print(f"candidates = {', '.join(v for v, _ in candidates)}")

    for attempt, (ver, anchors) in enumerate(candidates, 1):
        print(f"\n--- attempt {attempt}/{len(candidates)}: hooks for WeChat {ver} "
              f"(entry=0x{anchors.entry:X}) ---")
        rc = _attempt(exe, anchors, account_id, message_db, observe, auto)
        if rc == 0:
            return 0
        if rc == 4:
            print(f"    no codec activity with {ver} hooks -- trying the next version")
            continue
        return rc
    print("\nNO KEY CAPTURED (all registered versions tried)")
    return 4


def _attempt(exe: Path, anchors, account_id: str, message_db: Path,
             observe: int, auto: bool) -> int:
    """Run one capture attempt with one anchor set. Returns 0 on success, 4 on no-fire."""
    pid = None
    session = None
    script = None
    found: KeyInfo | None = None
    fires: dict[str, int] = {}
    stop = threading.Event()
    clicker: threading.Thread | None = None

    def log(msg: str) -> None:
        print(msg, flush=True)

    try:
        try:
            pid = frida.spawn(str(exe), cwd=str(exe.parent))
        except TypeError:
            pid = frida.spawn(str(exe))
        print(f"[spawned] pid={pid}")
        session = frida.attach(pid)

        def on_message(message, data):
            nonlocal found
            if message["type"] == "error":
                print(f"[js-error] {str(message.get('description'))[:200]}")
                return
            p = message.get("payload")
            if not isinstance(p, dict):
                return
            t = p.get("t")
            if t == "armed":
                print(f"[armed] {p['label']}")
            elif t == "armfail":
                print(f"[armfail] {p['label']}: {p.get('err')}")
            elif t == "armdone":
                print(f"[armdone] ok={p.get('ok')} fail={p.get('fail')}")
            elif t == "hit":
                label = p["label"]
                fires[label] = fires.get(label, 0) + 1
                blob = p.get("rcx")
                if fires[label] <= 2:
                    prev = bytes(blob[:16]).hex() if blob else "(none)"
                    print(f"[HIT #{fires[label]}] {label}  rcx[:16]={prev}")
                if found is None and blob:
                    cands = [bytes(blob[:32])]
                    for off in range(0, min(len(blob), 0x100) - 31, 8):
                        cands.append(bytes(blob[off : off + 32]))
                    for i, cand in enumerate(cands):
                        if found is not None:
                            break
                        if _verify_live(cand, message_db):
                            found = KeyInfo(
                                account_id=account_id,
                                wechat_version=anchors.wechat_version,
                                password=cand,
                                source="frida-keyagent",
                                verified=True,
                            )
                            print(f"[KEY FOUND] cand#{i} fp={found.fingerprint} HMAC VALID")
                            stop.set()

        script = session.create_script(
            JS_TEMPLATE % (anchors.entry, anchors.mmv1_ref, anchors.magic_check)
        )
        script.on("message", on_message)
        script.load()
        frida.resume(pid)
        print("[resumed] waiting for login / DB open ...")

        if auto:
            clicker = threading.Thread(
                target=clicker_loop, args=(pid, stop, log), daemon=True
            )
            clicker.start()

        deadline = time.time() + observe
        while time.time() < deadline and found is None:
            time.sleep(0.4)

        stop.set()
        print(f"\nfires = {fires or '{}'}")
        if found is None:
            return 4
        target = keystore.store_key(found)
        print(f"KEY fp={found.fingerprint} version={found.wechat_version}")
        print(f"stored -> {target}")
        return 0
    finally:
        stop.set()
        try:
            if script is not None:
                script.unload()
        except Exception:
            pass
        try:
            if session is not None:
                session.detach()
        except Exception:
            pass
        if pid:
            try:
                frida.get_local_device().kill(pid)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
