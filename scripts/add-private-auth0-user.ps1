param([string]$ResultPath)
# Run with PowerShell 7 on Windows. Passwords travel only in memory and CLI stdin.
# No password is passed as an argument, persisted, or included in error output.
# Requires an existing deployed/bound Action and database with signup disabled.
# Auth0 does not return secret values: successful update/deploy verifies the write,
# while reading back the literal ALLOWED_USER_IDS value is not supported.
#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
if ($ResultPath) { @{status='awaiting_input'} | ConvertTo-Json | Set-Content -LiteralPath $ResultPath }
$tenant = 'dev-7hq02dz6g07g73nf.us.auth0.com'
$cli = (Get-Command auth0 -ErrorAction SilentlyContinue).Source
if (!$cli) { $cli = Join-Path $env:LOCALAPPDATA 'Programs/Auth0/auth0.exe' }
function Api($Method, $Path, $Body = $null) {
    $start = [Diagnostics.ProcessStartInfo]::new($cli)
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    foreach ($arg in @('--tenant', $tenant, '--agent-mode', 'api', $Method, $Path)) { $start.ArgumentList.Add($arg) }
    if ($null -ne $Body) { $start.ArgumentList.Add('--data'); $start.ArgumentList.Add('@-') }
    $process = [Diagnostics.Process]::Start($start)
    $outputTask = $process.StandardOutput.ReadToEndAsync()
    $errorTask = $process.StandardError.ReadToEndAsync()
    if ($null -ne $Body) { $process.StandardInput.Write(($Body | ConvertTo-Json -Depth 40 -Compress)) }
    $process.StandardInput.Close()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        $errorText = $errorTask.GetAwaiter().GetResult()
        $reason = 'API request rejected'
        if ($errorText -match '(?i)password.*(strength|policy|weak|dictionary|requirements|invalid)') { $reason = 'Password rejected by tenant policy' }
        elseif ($errorText -match '(?i)(403|insufficient_scope|insufficient scope|permission)') { $reason = 'Insufficient Management API permissions' }
        elseif ($errorText -match '(?i)(409|already exists)') { $reason = 'User already exists; rerun to look up existing user' }
        elseif ($errorText -match '(?i)(401|unauthorized|expired)') { $reason = 'CLI authentication expired or unauthorized' }
        throw $reason
    }
    $raw = $outputTask.GetAwaiter().GetResult()
    if ($raw) { $raw | ConvertFrom-Json -Depth 60 }
}
Add-Type -AssemblyName System.Windows.Forms
function Prompt($Title, $Label, [bool]$Password = $false) {
    $form = [Windows.Forms.Form]::new()
    $form.Text = $Title; $form.Width = 510; $form.Height = 175
    $form.StartPosition = 'CenterScreen'; $form.TopMost = $true
    $labelControl = [Windows.Forms.Label]::new()
    $labelControl.Text = $Label; $labelControl.SetBounds(15, 12, 465, 35)
    $inputControl = [Windows.Forms.TextBox]::new()
    $inputControl.SetBounds(15, 50, 465, 25); $inputControl.UseSystemPasswordChar = $Password
    $button = [Windows.Forms.Button]::new()
    $button.Text = 'Continue'; $button.SetBounds(370, 85, 110, 30)
    $button.DialogResult = [Windows.Forms.DialogResult]::OK
    $form.Controls.AddRange(@($labelControl, $inputControl, $button)); $form.AcceptButton = $button
    try {
        # Consume Windows' inherited SW_HIDE startup flag before the modal dialog.
        $form.Show(); $form.Hide()
        if ($form.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { throw 'Input cancelled.' }
        return $inputControl.Text
    } finally { $inputControl.Clear(); $form.Dispose() }
}
$stage = 'tenant preflight'
try {
    $envPath = Join-Path $PSScriptRoot '../.env'
    $envHash = (Get-FileHash -LiteralPath $envPath -Algorithm SHA256).Hash
    $clientsBefore = @(Api get 'clients?per_page=100') | ConvertTo-Json -Depth 60 -Compress
    $actions = @((Api get 'actions/actions?per_page=100').actions | Where-Object name -eq 'ACMP Connect Private Login')
    $bindings = Api get 'actions/triggers/post-login/bindings'
    $dbs = @(Api get 'connections?per_page=100' | Where-Object { $_.name -eq 'Username-Password-Authentication' -and $_.strategy -eq 'auth0' })
    if ($actions.Count -ne 1 -or !$actions[0].deployed_version -or
        $actions[0].id -notin $bindings.bindings.action.id -or
        $dbs.Count -ne 1 -or !$dbs[0].options.disable_signup -or $dbs[0].options.requires_username) {
        throw 'Tenant prerequisites failed; no user or settings changed.'
    }
    $stage = 'email input'
    $email = (Prompt 'ACMP Connect - private Auth0 user' 'Enter your email (Auth0 login).').Trim()
    $stage = 'email validation'
    $null = [Net.Mail.MailAddress]::new($email)
    $stage = 'existing user lookup'
    $users = @(Api get ('users-by-email?email=' + [uri]::EscapeDataString($email)))
    $users = @($users | Where-Object { @($_.identities.connection) -contains 'Username-Password-Authentication' })
    if ($users.Count -gt 1) { throw 'Ambiguous database user.' }
    if ($users.Count -eq 1) { $user = $users[0] } else {
        $stage = 'password input'
        $password = Prompt 'ACMP Connect - new Auth0 password' 'New password: 12+ characters; upper/lowercase, number, symbol.' $true
        try {
            $stage = 'user creation'
            $user = Api post 'users' @{connection='Username-Password-Authentication'; email=$email; password=$password; verify_email=$false; email_verified=$false}
        } finally { $password = $null }
    }
    if (!$user.user_id -or $user.blocked) { throw 'User is missing or blocked.' }
    $stage = 'allowlist configuration'
    & (Join-Path $PSScriptRoot 'configure-auth0.ps1') -Tenant $tenant -AllowedUserIds @($user.user_id) -AllowlistOnly | Out-Null
    $stage = 'configuration preservation check'
    $clientsAfter = @(Api get 'clients?per_page=100') | ConvertTo-Json -Depth 60 -Compress
    if ($clientsBefore -cne $clientsAfter -or $envHash -ne (Get-FileHash -LiteralPath $envPath -Algorithm SHA256).Hash) {
        throw 'Application or .env snapshot changed; inspect configuration before continuing.'
    }
    if ($ResultPath) { @{status='configured'; user_id=$user.user_id; applications_unchanged=$true; env_unchanged=$true; allowlist_write_verified=$true} | ConvertTo-Json | Set-Content -LiteralPath $ResultPath }
    [Windows.Forms.MessageBox]::Show('Private user configured. You can return to Codex.', 'ACMP Connect') | Out-Null
} catch {
    # Never surface arbitrary API/runtime errors: they may contain request data.
    $reason = 'Details suppressed to protect credentials'
    if ($_.Exception.Message -in @('Input cancelled.', 'API request rejected', 'Password rejected by tenant policy', 'Insufficient Management API permissions', 'User already exists; rerun to look up existing user', 'CLI authentication expired or unauthorized')) { $reason = $_.Exception.Message }
    if ($ResultPath) { @{status='failed'; stage=$stage; reason=$reason} | ConvertTo-Json | Set-Content -LiteralPath $ResultPath }
    [Windows.Forms.MessageBox]::Show("Setup stopped at: $stage. $reason. Return to Codex.", 'ACMP Connect - setup stopped') | Out-Null
}
