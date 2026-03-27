Register this terminal with EyeClaude for eye-tracking focus management.

First, capture this terminal's window handle, then register it:

```bash
HWND=$(powershell -NoProfile -Command "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class W { [DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow(); }'; [W]::GetForegroundWindow().ToInt64()") && eyeclaude register --hwnd "$HWND"
```

Confirm registration was successful by telling me the output.
