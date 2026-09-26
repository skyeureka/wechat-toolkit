$errors = $null
$tokens = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
  "T:\wx4win\wechat-toolkit\scripts\click_enter.ps1", [ref]$tokens, [ref]$errors
)
if ($errors -and $errors.Count -gt 0) {
  Write-Output "PS1 PARSE ERRORS:"
  $errors | ForEach-Object { "  line $($_.Extent.StartLineNumber): $($_.Message)" }
} else {
  Write-Output "PS1 PARSE OK"
}
