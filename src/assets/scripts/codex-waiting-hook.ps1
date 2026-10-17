# Codex hook for YASB's Codex pet: marks a session as waiting for approval. Observe only:
# it prints nothing and always exits 0, so Codex shows its normal prompt.
$ErrorActionPreference = 'SilentlyContinue'
try {
    $hook = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $id = [string]$hook.session_id
    if ($id -notmatch '^[0-9A-Za-z-]{8,64}$') { exit 0 }
    $dir = Join-Path $env:LOCALAPPDATA 'YASB\codex-waiting'
    $file = Join-Path $dir "$id.json"
    if ($hook.hook_event_name -eq 'PermissionRequest') {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $marker = @{
            turn_id = [string]$hook.turn_id
            tool_name = [string]$hook.tool_name
            at_ms = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        }
        $marker | ConvertTo-Json -Compress | Set-Content -LiteralPath $file -Encoding UTF8
    } else {
        Remove-Item -LiteralPath $file -Force
    }
} catch {}
exit 0
