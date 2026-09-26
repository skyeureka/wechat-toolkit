param(
  # NOTE: not named $Pid -- that is a read-only PowerShell automatic variable.
  [Parameter(Mandatory=$true)][int]$TargetPid,
  [switch]$Quiet
)
# Clicks the "进入微信" green button on the WeChat account-picker window.
#
# Targets ONLY the given pid, so a user's own WeChat session is never touched.
#
# A plain SetCursorPos + mouse_event is NOT enough: those are screen coordinates and
# land on whatever window is actually on top (observed hitting Chrome when WeChat sat
# behind it), which silently does nothing while looking like a successful click.
# So: raise the target window first, then verify via WindowFromPoint that the click
# point really belongs to TargetPid before sending it. A click is only reported when
# it landed on the intended window.
#
# Emits: CLICKED <x> <y> | NOWINDOW | NOBUTTON | OCCLUDED <pid>
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class W32 {
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr SetActiveWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  public static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
  public static readonly IntPtr HWND_NOTOPMOST = new IntPtr(-2);
  public const uint SWP_NOMOVE = 0x0002;
  public const uint SWP_NOSIZE = 0x0001;
  public const uint SWP_NOACTIVATE = 0x0010;
  public const uint SWP_SHOWWINDOW = 0x0040;
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
}
"@
[void][W32]::SetProcessDPIAware()

function Get-GreenButton($hwnd, $w, $h) {
  Add-Type -AssemblyName System.Drawing
  $bmp = New-Object System.Drawing.Bitmap($w, $h)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $hdc = $g.GetHdc()
  [void][W32]::PrintWindow($hwnd, $hdc, 2)
  $g.ReleaseHdc($hdc); $g.Dispose()
  $minX=99999;$minY=99999;$maxX=-1;$maxY=-1;$hits=0
  for ($y=0; $y -lt $h; $y+=2) {
    for ($x=0; $x -lt $w; $x+=2) {
      $c = $bmp.GetPixel($x,$y)
      # WeChat brand green ~ #07C160
      if ($c.G -gt 140 -and $c.G -lt 225 -and $c.R -lt 90 -and $c.B -gt 60 -and $c.B -lt 150) {
        $hits++
        if ($x -lt $minX){$minX=$x}; if ($x -gt $maxX){$maxX=$x}
        if ($y -lt $minY){$minY=$y}; if ($y -gt $maxY){$maxY=$y}
      }
    }
  }
  $bmp.Dispose()
  if ($hits -lt 200) { return $null }
  return [pscustomobject]@{ MinX=$minX; MinY=$minY; MaxX=$maxX; MaxY=$maxY; Hits=$hits }
}

$target = $null
$cb = [W32+EnumProc]{
  param($h, $l)
  $p = 0
  [void][W32]::GetWindowThreadProcessId($h, [ref]$p)
  if ([int]$p -eq $TargetPid -and [W32]::IsWindowVisible($h)) {
    $r = New-Object W32+RECT
    [void][W32]::GetWindowRect($h, [ref]$r)
    $w = $r.Right - $r.Left; $ht = $r.Bottom - $r.Top
    if ($w -gt 200 -and $ht -gt 200) {
      $script:target = [pscustomobject]@{ Hwnd=$h; L=$r.Left; T=$r.Top; W=$w; H=$ht }
    }
  }
  return $true
}
[void][W32]::EnumWindows($cb, [IntPtr]::Zero)
if (-not $target) {
  if (-not $Quiet) { Write-Output "NOWINDOW" }
  exit 3
}

$btn = Get-GreenButton $target.Hwnd $target.W $target.H
if (-not $btn) {
  if (-not $Quiet) { Write-Output "NOBUTTON" }
  exit 4
}

$cx = $target.L + [int](($btn.MinX + $btn.MaxX) / 2)
$cy = $target.T + [int](($btn.MinY + $btn.MaxY) / 2)

# --- Guarantee nothing occludes the target before clicking ---
# SetForegroundWindow is unreliable from a background process (Windows blocks foreground
# stealing), and a screen-coordinate click then lands on whatever IS on top -- observed
# hitting Chrome. SetWindowPos with HWND_TOPMOST needs no foreground rights, so use it to
# raise the window, and restore NOTOPMOST afterwards.
if ([W32]::IsIconic($target.Hwnd)) { [void][W32]::ShowWindow($target.Hwnd, 9) }  # SW_RESTORE
[void][W32]::ShowWindow($target.Hwnd, 5)   # SW_SHOW
$flags = [W32]::SWP_NOMOVE -bor [W32]::SWP_NOSIZE -bor [W32]::SWP_SHOWWINDOW
[void][W32]::SetWindowPos($target.Hwnd, [W32]::HWND_TOPMOST, 0, 0, 0, 0, $flags)
# best-effort foreground too (harmless if refused)
[void][W32]::SetForegroundWindow($target.Hwnd)
Start-Sleep -Milliseconds 400

# --- verify the click point really belongs to our target ---
$pt = New-Object W32+POINT
$pt.X = $cx; $pt.Y = $cy
$under = [W32]::WindowFromPoint($pt)
$underPid = 0
[void][W32]::GetWindowThreadProcessId($under, [ref]$underPid)
if ([int]$underPid -ne $TargetPid) {
  [void][W32]::SetWindowPos($target.Hwnd, [W32]::HWND_NOTOPMOST, 0, 0, 0, 0, $flags)
  if (-not $Quiet) { Write-Output "OCCLUDED $underPid" }
  exit 5
}

[void][W32]::SetCursorPos($cx, $cy)
Start-Sleep -Milliseconds 200
[W32]::mouse_event(0x0002,0,0,0,[IntPtr]::Zero)
Start-Sleep -Milliseconds 70
[W32]::mouse_event(0x0004,0,0,0,[IntPtr]::Zero)
Start-Sleep -Milliseconds 300
# restore normal z-order so the user's desktop is left as it was
[void][W32]::SetWindowPos($target.Hwnd, [W32]::HWND_NOTOPMOST, 0, 0, 0, 0, $flags)
Write-Output "CLICKED $cx $cy"
