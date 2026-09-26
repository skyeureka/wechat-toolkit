"""WeChat 4.x Windows chat-history toolkit -- one-click orchestrator.

Wraps the (MIT) ChatTrace engine with the Windows-specific fixes this project proved:
  * version-agnostic anchor location for Weixin.dll (works on 4.1.15.12, not just 4.1.12.55)
  * key capture that spawns WeChat with the correct working directory
  * account-picker auto-click so an unattended capture actually completes
  * incremental decrypt + local Web UI

Flow: doctor -> locate anchors -> capture key (if missing) -> decrypt -> Web UI.

Usage:
    python run.py              # full flow, opens the Web UI
    python run.py --check      # environment + readiness report only
    python run.py --capture    # force a fresh key capture
    python run.py --no-ui      # do everything except starting the Web UI
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def hr(title: str = "") -> None:
    print("\n" + "=" * 68)
    if title:
        print(title)
        print("=" * 68)


def find_accounts() -> list[Path]:
    """Locate xwechat_files roots and the account dirs inside them."""
    from chattrace.keyagent.account import discover_accounts

    candidates: list[Path] = []
    for drive in ("C:", "D:", "E:", "F:", "T:"):
        for sub in ("xwechat_files", "WeChat Files"):
            p = Path(f"{drive}/{sub}")
            if p.exists():
                candidates.append(p)
    docs = Path.home() / "Documents" / "xwechat_files"
    if docs.exists():
        candidates.append(docs)

    out: list[Path] = []
    for root in candidates:
        for acc in discover_accounts(root):
            out.append(acc.account_dir)
    return out


def pick_account(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if (p / "db_storage" / "message" / "message_0.db").exists() else None
    accs = find_accounts()
    if not accs:
        return None
    if len(accs) == 1:
        return accs[0]
    # newest first, matching chatlog semantics
    accs.sort(key=lambda p: (p / "db_storage" / "message" / "message_0.db").stat().st_mtime,
              reverse=True)
    print("multiple WeChat accounts found:")
    for i, a in enumerate(accs, 1):
        print(f"  [{i}] {a.name}")
    try:
        raw = input(f"pick one [1-{len(accs)}] (default 1): ").strip() or "1"
        return accs[int(raw) - 1]
    except (ValueError, IndexError, EOFError):
        return accs[0]


def ensure_anchors(py: str) -> bool:
    """Register anchors for every installed WeChat version that lacks them."""
    from chattrace.keyagent import version_map
    from chattrace.keyagent.locate_anchors import LocateError, locate_anchors
    from chattrace.keyagent.wechat_state import (
        find_weixin_exe,
        installed_wechat_versions,
    )

    exe = find_weixin_exe()
    if exe is None:
        print("  !! Weixin.exe not found -- is WeChat installed?")
        return False

    versions = installed_wechat_versions()
    if not versions:
        print("  !! no versioned Weixin.dll found next to Weixin.exe")
        return False

    pending = [(v, d) for v, d in versions if version_map.resolve_anchors(v) is None]
    if not pending:
        print(f"  ok  anchors already registered for {', '.join(v for v, _ in versions)}")
        return True

    ok = True
    for ver, dll in pending:
        print(f"  locating anchors for {ver} ...")
        try:
            a = locate_anchors(dll, wechat_version=ver)
        except LocateError as exc:
            print(f"  !! {ver}: {exc}")
            ok = False
            continue
        version_map.save_anchor_cache([a])
        print(f"  ok  {ver}: entry=0x{a.entry:X} mmv1_ref=0x{a.mmv1_ref:X} "
              f"magic=0x{a.magic_check:X}")
    return ok


def have_key(account_dir: Path) -> bool:
    from chattrace.keyagent import keystore
    from chattrace.keyagent.wechat_state import installed_wechat_versions

    for ver, _ in installed_wechat_versions():
        try:
            info = keystore.load_key(account_dir.name, ver)
            if info.password:
                return True
        except Exception:
            continue
    try:
        return bool(keystore.load_key(account_dir.name).password)
    except Exception:
        return False


def weixin_running() -> bool:
    from chattrace.keyagent.wechat_state import is_weixin_running

    return is_weixin_running()


def close_weixin() -> None:
    """Gracefully close any running WeChat so a capture can be spawned."""
    try:
        subprocess.run(
            ["taskkill", "/IM", "Weixin.exe", "/T"],
            capture_output=True, timeout=30, check=False,
        )
    except Exception:
        pass
    deadline = time.time() + 20
    while time.time() < deadline and weixin_running():
        time.sleep(0.5)


def cmd_check(account_dir: Path | None) -> int:
    hr("environment check")
    problems = 0

    print(f"python      : {sys.version.split()[0]}")
    for mod in ("frida", "Cryptodome", "zstandard"):
        try:
            m = __import__(mod)
            print(f"  ok  {mod} {getattr(m, '__version__', '')}")
        except Exception as exc:
            print(f"  !!  {mod}: {exc}")
            problems += 1

    from chattrace.keyagent.wechat_state import (
        find_weixin_exe,
        installed_wechat_versions,
        is_weixin_running,
    )

    exe = find_weixin_exe()
    print(f"weixin.exe  : {exe or 'NOT FOUND'}")
    if exe is None:
        problems += 1
    print(f"running     : {'yes' if is_weixin_running() else 'no'}")

    if not ensure_anchors(sys.executable):
        problems += 1

    if account_dir is None:
        print("account     : NOT FOUND")
        problems += 1
    else:
        print(f"account     : {account_dir.name}")
        print(f"              {account_dir}")
        print(f"key stored  : {'yes' if have_key(account_dir) else 'no (will capture)'}")

    hr("summary")
    print("ready" if problems == 0 else f"{problems} issue(s) -- see above")
    return 0 if problems == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="WeChat 4.x Windows chat toolkit")
    ap.add_argument("--account-dir", default=None, help="Account dir (auto-detected if omitted)")
    ap.add_argument("--check", action="store_true", help="Readiness report only; no changes")
    ap.add_argument("--capture", action="store_true", help="Force a fresh key capture")
    ap.add_argument("--no-ui", action="store_true", help="Skip launching the Web UI")
    ap.add_argument("--port", type=int, default=8714)
    ap.add_argument("--export-format", choices=("txt", "json", "html"), default=None,
                    help="Export a single chat then exit (needs --user)")
    ap.add_argument("--user", default=None, help="Chat username for --export-format")
    args = ap.parse_args()

    account_dir = pick_account(args.account_dir)

    if args.check:
        return cmd_check(account_dir)

    if account_dir is None:
        hr("account not found")
        print("Could not find any WeChat account directory.")
        print("Expected: <Documents>\\xwechat_files\\<wxid_...>\\db_storage\\message\\message_0.db")
        print("Pass one explicitly with --account-dir.")
        return 1

    hr("WeChat chat-history toolkit (Windows)")
    print(f"account: {account_dir}")
    print(f"        {account_dir.name}")

    # ---- 1. anchors ----
    hr("1/4  locating codec anchors")
    if not ensure_anchors(sys.executable):
        print("\nCannot continue without anchors for your WeChat version.")
        return 1

    # ---- 2. key ----
    hr("2/4  database key")
    need_capture = args.capture or not have_key(account_dir)
    if need_capture:
        if weixin_running():
            print("  WeChat is running; closing it so a capture instance can start ...")
            close_weixin()
        print("  capturing key (spawns a temporary WeChat; clicks its account picker; then closes it) ...")
        from chattrace.keyagent.account import resolve_account
        from chattrace.service.keycapture import CaptureService

        def on_progress(stage: str, payload=None) -> None:
            if stage == "attempt":
                print(f"  trial {payload}")
            elif stage in ("spawned", "module-loaded", "resumed", "key-found", "stored",
                           "autoclick", "autoclick-error", "retry", "cross-check"):
                print(f"    [{stage}] {payload}")
            elif stage == "armed":
                print(f"    [armed] {payload}")

        try:
            acct = resolve_account(account_dir)
            key = CaptureService.run(
                acct, observe_ms=180_000, store=True, progress=on_progress
            )
            print(f"  ok  key captured: fp={key.fingerprint} (WeChat {key.wechat_version})")
        except Exception as exc:
            print(f"\n  !! key capture failed: {exc}")
            print("     Make sure WeChat has been signed in normally at least once, then retry.")
            return 1
    else:
        print("  ok  a stored key already opens this account's databases")

    # ---- 3. decrypt ----
    hr("3/4  decrypting databases")
    r = subprocess.run(
        [sys.executable, "-m", "chattrace", "data", "decrypt", "--account-dir", str(account_dir)]
    )
    if r.returncode != 0:
        print("\n  !! decryption failed")
        return r.returncode

    # ---- 4. export or UI ----
    if args.export_format:
        if not args.user:
            print("!! --export-format requires --user <username>")
            return 2
        hr("4/4  exporting chat")
        return subprocess.run(
            [sys.executable, "-m", "chattrace", "export",
             "--account-dir", str(account_dir),
             "--user", args.user, "--format", args.export_format, "--media"]
        ).returncode

    if args.no_ui:
        hr("done")
        print("Databases decrypted. Browse them with:")
        print(f"  {sys.executable} -m chattrace webui")
        return 0

    hr("4/4  launching Web UI")
    print(f"  http://127.0.0.1:{args.port}/")
    print("  (press Ctrl+C to stop)")
    return subprocess.run(
        [sys.executable, "-m", "chattrace", "webui", "--host", "127.0.0.1",
         "--port", str(args.port)]
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
