Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class W32 {
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
}
"@
[void][W32]::SetProcessDPIAware()
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$pids = @(Get-Process -Name Weixin -ErrorAction SilentlyContinue | ForEach-Object { [uint32]$_.Id })
Write-Output "Weixin pids: $($pids -join ',')"

$cb = [W32+EnumProc]{
  param($h, $l)
  $p = 0
  [void][W32]::GetWindowThreadProcessId($h, [ref]$p)
  if ($pids -contains [uint32]$p) {
    $r = New-Object W32+RECT
    [void][W32]::GetWindowRect($h, [ref]$r)
    $sb = New-Object System.Text.StringBuilder 256
    [void][W32]::GetWindowTextW($h, $sb, 256)
    $cn = New-Object System.Text.StringBuilder 128
    [void][W32]::GetClassNameW($h, $cn, 128)
    $w = $r.Right-$r.Left; $ht = $r.Bottom-$r.Top
    if ($w -gt 100 -and $ht -gt 100) {
      $fg = [W32]::GetForegroundWindow()
      Write-Output ("hwnd={0} pid={1} vis={2} {3}x{4} at ({5},{6}) fg={7} class='{8}' title='{9}'" -f `
        $h, $p, [W32]::IsWindowVisible($h), $w, $ht, $r.Left, $r.Top, ($h -eq $fg), $cn.ToString(), $sb.ToString())
    }
  }
  return $true
}
[void][W32]::EnumWindows($cb, [IntPtr]::Zero)

# what is actually at the click point?
$pt = New-Object W32+POINT
$pt.X = 959; $pt.Y = 619
$under = [W32]::WindowFromPoint($pt)
$up = 0
[void][W32]::GetWindowThreadProcessId($under, [ref]$up)
$usb = New-Object System.Text.StringBuilder 256
[void][W32]::GetWindowTextW($under, $usb, 256)
$ucn = New-Object System.Text.StringBuilder 128
[void][W32]::GetClassNameW($under, $ucn, 128)
$uname = (Get-Process -Id $up -ErrorAction SilentlyContinue).ProcessName
Write-Output ""
Write-Output "WindowFromPoint(959,619) -> hwnd=$under pid=$up proc=$uname class='$($ucn.ToString())' title='$($usb.ToString())'"
$fg = [W32]::GetForegroundWindow()
$fpid = 0
[void][W32]::GetWindowThreadProcessId($fg, [ref]$fpid)
Write-Output "foreground hwnd=$fg pid=$fpid proc=$((Get-Process -Id $fpid -ErrorAction SilentlyContinue).ProcessName)"
