# RM-3 lane 1: open a PMM in the normal GUI, move to a frame, and save the
# project as a new PMM, the way a user would. Run it in the console session
# (on an OpenSSH host, through a one-shot `schtasks /Create /IT` task),
# because the GUI needs a desktop and real keyboard input.
# Usage: gui_save.ps1 -Exe <MikuDanceStudio.exe> -Pmm <in.pmm> -Out <out.pmm> [-Frame 600]
# Exit 0 when the file is saved; prints its sha256.
param([Parameter(Mandatory)][string]$Exe, [Parameter(Mandatory)][string]$Pmm,
      [Parameter(Mandatory)][string]$Out, [int]$Frame = 600)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ErrorActionPreference = 'Continue'
Add-Type @'
using System; using System.Text; using System.Runtime.InteropServices;
public static class U {
  [DllImport("user32.dll")] public static extern IntPtr GetDlgItem(IntPtr h, int id);
  [DllImport("user32.dll")] public static extern IntPtr SendMessageW(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern IntPtr SendMessageW(IntPtr h, uint m, IntPtr w, StringBuilder l);
  [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, int x, int y, uint d, IntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint f, IntPtr e);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassNameW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc p, IntPtr l);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] struct KI { public ushort vk, scan; public uint flags, time; public IntPtr extra; }
  [StructLayout(LayoutKind.Explicit, Size=40)] struct IN { [FieldOffset(0)] public uint type; [FieldOffset(8)] public KI k; }
  [DllImport("user32.dll")] static extern uint SendInput(uint n, IN[] i, int size);
  static string Cls(IntPtr h) { var s = new StringBuilder(64); GetClassNameW(h, s, 64); return s.ToString(); }
  public static string Title(IntPtr h) { var s = new StringBuilder(512); GetWindowTextW(h, s, 512); return s.ToString(); }
  public static string Get(IntPtr h) { var s = new StringBuilder(512); SendMessageW(h, 0x000D, (IntPtr)512, s); return s.ToString(); }
  public static IntPtr FindTop(uint pid, string cls) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => { uint p; GetWindowThreadProcessId(h, out p);
      if (p == pid && IsWindowVisible(h) && Cls(h) == cls) { found = h; return false; } return true; }, IntPtr.Zero);
    return found;
  }
  public static void Type(string text) {
    foreach (char c in text) {
      var down = new IN { type = 1, k = new KI { scan = c, flags = 4 } };
      var up = new IN { type = 1, k = new KI { scan = c, flags = 6 } };
      SendInput(2, new[] { down, up }, Marshal.SizeOf(typeof(IN)));
      System.Threading.Thread.Sleep(30);
    }
  }
}
'@
function Key([byte]$vk) { [U]::keybd_event($vk, 0, 0, [IntPtr]::Zero); Start-Sleep -Milliseconds 60; [U]::keybd_event($vk, 0, 2, [IntPtr]::Zero); Start-Sleep -Milliseconds 120 }
function Click([IntPtr]$h) {
  $r = New-Object U+RECT; [void][U]::GetWindowRect($h, [ref]$r)
  [void][U]::SetCursorPos([int](($r.L + $r.R) / 2), [int](($r.T + $r.B) / 2))
  [U]::mouse_event(2, 0, 0, 0, [IntPtr]::Zero); Start-Sleep -Milliseconds 60; [U]::mouse_event(4, 0, 0, 0, [IntPtr]::Zero); Start-Sleep -Milliseconds 300
}
function WaitTop($id, $cls, $tries) { for ($i = 0; $i -lt $tries; $i++) { $h = [U]::FindTop($id, $cls); if ($h -ne [IntPtr]::Zero) { return $h }; Start-Sleep -Milliseconds 200 }; [IntPtr]::Zero }

if (Test-Path $Out) { Write-Error "output exists: $Out"; exit 1 }
$p = Start-Process $Exe -ArgumentList "`"$Pmm`"" -PassThru -WorkingDirectory (Split-Path $Exe)
$null = $p.Handle
try {
  $main = WaitTop $p.Id 'Polygon Movie Maker' 150
  if ($main -eq [IntPtr]::Zero) { Write-Error 'no main window'; exit 1 }
  "main window: $([U]::Title($main))"
  Start-Sleep -Seconds 4
  $dialog = [U]::FindTop($p.Id, '#32770')
  if ($dialog -ne [IntPtr]::Zero) { Write-Error "dialog while loading: $([U]::Title($dialog))"; exit 1 }

  # The app reads Enter by polling the keyboard, so the frame needs real input.
  $edit = [U]::GetDlgItem($main, 417)   # current-frame edit
  [void][U]::SetForegroundWindow($main); Start-Sleep -Milliseconds 300
  Click $edit
  # Clear with End + Backspace; a selection made by EM_SETSEL does not survive the click.
  Key 0x23; for ($i = 0; $i -lt 12; $i++) { Key 0x08 }
  [U]::Type("$Frame"); Key 0x0D
  Start-Sleep -Seconds 2
  "frame: $([U]::Get($edit))"
  if ([U]::Get($edit) -ne "$Frame") { Write-Error 'frame did not change'; exit 1 }

  [void][U]::PostMessageW($main, 0x111, [IntPtr]0xD0, [IntPtr]::Zero)   # File > Save As
  $save = WaitTop $p.Id '#32770' 50
  if ($save -eq [IntPtr]::Zero) { Write-Error 'no save dialog'; exit 1 }
  Start-Sleep -Seconds 2
  # The dialog opens with focus in the file-name field. WM_SETTEXT does not
  # reach the dialog's own state, so type the path.
  [U]::keybd_event(0x11, 0, 0, [IntPtr]::Zero); Key 0x41; [U]::keybd_event(0x11, 0, 2, [IntPtr]::Zero)
  [U]::Type($Out); Key 0x0D
  for ($i = 0; $i -lt 50 -and -not (Test-Path $Out); $i++) { Start-Sleep -Milliseconds 200 }
  Start-Sleep -Seconds 1
  if (-not (Test-Path $Out)) { Write-Error "not saved; open dialog: $([U]::Title([U]::FindTop($p.Id, '#32770')))"; exit 1 }
  "saved: $Out $((Get-Item $Out).Length) bytes sha256 $((Get-FileHash $Out).Hash)"
} finally {
  Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}
