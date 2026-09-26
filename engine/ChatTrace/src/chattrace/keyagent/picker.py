"""Find and click the WeChat account-picker button, in-process (no PowerShell).

Why this exists: Frida-spawned WeChat lands on the "进入微信" account picker and waits,
so an unattended capture never reaches the codec path. Clicking it needs care:

* Screen-coordinate clicks land on whatever window is actually on top. Observed hitting
  a browser window while WeChat sat behind it -- the click "succeeded" and did nothing.
  So raise the target window first and verify the click point belongs to the target pid.
* SetForegroundWindow is unreliable from a background process (Windows blocks foreground
  stealing). SetWindowPos with HWND_TOPMOST needs no such rights, so raise with that and
  restore the normal z-order afterwards.
* Only windows belonging to the pid we spawned are ever touched.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time
from dataclasses import dataclass

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

# WeChat brand green (#07C160). The DIB read back gives r=0 for the button fill, so
# bounds must be INCLUSIVE on the low end -- an exclusive `0 < r` excludes every pixel.
GREEN_MIN = (0, 140, 50)
GREEN_MAX = (95, 235, 165)

HWND_TOPMOST = wt.HWND(-1)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040
SW_RESTORE = 9
SW_SHOW = 5
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


@dataclass
class PickerWindow:
    hwnd: int
    pid: int
    left: int
    top: int
    width: int
    height: int


@dataclass
class ClickResult:
    status: str          # clicked | no_window | no_button | occluded
    x: int = 0
    y: int = 0
    occluded_by: int = 0


_EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)


def _dpi_aware() -> None:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def find_picker_window(pid: int, min_side: int = 200) -> PickerWindow | None:
    """The largest visible top-level window owned by pid (the picker/login window)."""
    _dpi_aware()
    found: list[PickerWindow] = []

    def cb(hwnd, _lparam):
        wpid = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        r = _RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return True
        w = r.right - r.left
        h = r.bottom - r.top
        if w > min_side and h > min_side:
            found.append(PickerWindow(int(hwnd), pid, r.left, r.top, w, h))
        return True

    user32.EnumWindows(_EnumProc(cb), 0)
    if not found:
        return None
    return max(found, key=lambda p: p.width * p.height)


def _window_bitmap(win: PickerWindow):
    """Snapshot the window via PrintWindow (works even when partially covered)."""
    hdc_win = user32.GetWindowDC(win.hwnd)
    if not hdc_win:
        return None
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, win.width, win.height)
    gdi32.SelectObject(hdc_mem, bmp)
    PW_RENDERFULLCONTENT = 0x00000002
    user32.PrintWindow(win.hwnd, hdc_mem, PW_RENDERFULLCONTENT)

    class _BMI(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    bmi = _BMI()
    bmi.biSize = ctypes.sizeof(_BMI)
    bmi.biWidth = win.width
    bmi.biHeight = -win.height        # top-down
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bmi.biCompression = 0              # BI_RGB
    buf_len = win.width * win.height * 4
    buf = ctypes.create_string_buffer(buf_len)

    # GetDIBits requires the bitmap NOT be selected into a DC, otherwise some drivers
    # hand back unmodified (blank) bits and the button is never found.
    old = gdi32.SelectObject(hdc_mem, gdi32.GetStockObject(0))  # 0 = WHITE_BRUSH
    got = gdi32.GetDIBits(hdc_mem, bmp, 0, win.height, buf, ctypes.byref(bmi), 0)
    if old:
        gdi32.SelectObject(hdc_mem, old)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(win.hwnd, hdc_win)
    if not got:
        return None
    return buf.raw, win.width, win.height


def dump_window_png(win: PickerWindow, path: str) -> bool:
    """Debug helper: write the window snapshot as a PNG (uses Pillow if present)."""
    shot = _window_bitmap(win)
    if shot is None:
        return False
    raw, w, h = shot
    try:
        from PIL import Image  # type: ignore
    except Exception:
        # no Pillow: write a minimal BMP instead
        import struct
        row = w * 4
        with open(path + ".bmp", "wb") as fh:
            size = 54 + row * h
            fh.write(b"BM" + struct.pack("<IHHI", size, 0, 0, 54))
            fh.write(struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 32, 0, row * h, 0, 0, 0, 0))
            fh.write(raw)
        return True
    img = Image.frombuffer("RGBA", (w, h), raw, "raw", "BGRA", 0, 1)
    img.convert("RGB").save(path)
    return True


# WHITE_BRUSH stock object id for SelectObject deselection
gdi32.GetStockObject.restype = wt.HGDIOBJ


def _find_green_button(win: PickerWindow, stride: int = 4):
    """Bounding box of the brand-green button, or None."""
    shot = _window_bitmap(win)
    if shot is None:
        return None
    raw, w, h = shot
    rmin, gmin, bmin = GREEN_MIN
    rmax, gmax, bmax = GREEN_MAX
    min_x, min_y, max_x, max_y, hits = w, h, -1, -1, 0
    # BGRA order in the DIB
    for y in range(0, h, stride):
        row = y * w * 4
        for x in range(0, w, stride):
            i = row + x * 4
            b = raw[i]
            g = raw[i + 1]
            r = raw[i + 2]
            if gmin <= g <= gmax and rmin <= r <= rmax and bmin <= b <= bmax and g > r + 40:
                hits += 1
                if x < min_x: min_x = x
                if x > max_x: max_x = x
                if y < min_y: min_y = y
                if y > max_y: max_y = y
    if hits < 120:
        return None
    return min_x, min_y, max_x, max_y, hits


def click_account_picker(pid: int) -> ClickResult:
    """Click the "进入微信" button in pid's picker window, if present."""
    win = find_picker_window(pid)
    if win is None:
        return ClickResult("no_window")

    box = _find_green_button(win)
    if box is None:
        return ClickResult("no_button")
    min_x, min_y, max_x, max_y, _hits = box
    cx = win.left + (min_x + max_x) // 2
    cy = win.top + (min_y + max_y) // 2

    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
    if user32.IsIconic(win.hwnd):
        user32.ShowWindow(win.hwnd, SW_RESTORE)
    user32.ShowWindow(win.hwnd, SW_SHOW)
    user32.SetWindowPos(win.hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
    user32.SetForegroundWindow(win.hwnd)   # best effort; may be refused
    time.sleep(0.35)

    # The click only counts if the point really belongs to the window we mean to hit.
    pt = _POINT(cx, cy)
    under = user32.WindowFromPoint(pt)
    under_pid = wt.DWORD(0)
    if under:
        user32.GetWindowThreadProcessId(under, ctypes.byref(under_pid))
    if under_pid.value != pid:
        user32.SetWindowPos(win.hwnd, wt.HWND(-2), 0, 0, 0, 0, flags)  # NOTOPMOST
        return ClickResult("occluded", cx, cy, under_pid.value)

    user32.SetCursorPos(cx, cy)
    time.sleep(0.12)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.3)
    user32.SetWindowPos(win.hwnd, wt.HWND(-2), 0, 0, 0, 0, flags)      # restore
    return ClickResult("clicked", cx, cy)
