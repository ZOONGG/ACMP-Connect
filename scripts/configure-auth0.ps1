param(
    [string]$Tenant = 'dev-7hq02dz6g07g73nf.us.auth0.com',
    [string]$Origin,
    [string]$ChatGPTCallback,
    [string[]]$AllowedUserIds,
    [switch]$AllowlistOnly
)
$ErrorActionPreference = 'Stop'
$cli = (Get-Command auth0 -ErrorAction SilentlyContinue).Source
if (!$cli) { $cli = Join-Path $env:LOCALAPPDATA 'Programs/Auth0/auth0.exe' }
function Api([string]$Method, [string]$Path, $Body = $null) {
    $cliArgs = @('--tenant', $Tenant, '--agent-mode', 'api', $Method, $Path)
    # Responses can contain credentials. Capture them in memory; never print raw JSON.
    if ($null -ne $Body) {
        $raw = ($Body | ConvertTo-Json -Depth 40 -Compress) | & $cli @cliArgs --data '@-'
    } else { $raw = & $cli @cliArgs }
    if ($LASTEXITCODE -ne 0) { throw "Auth0 request failed: $Method $Path (response suppressed)" }
    if ($raw) { return ($raw | ConvertFrom-Json -Depth 60) }
}
if ($AllowlistOnly) {
    if ($Origin -or $ChatGPTCallback -or @($AllowedUserIds).Count -ne 1 -or
        $AllowedUserIds[0] -notmatch '^auth0\|[^\s,]+$') {
        throw 'AllowlistOnly requires exactly one database user ID and no application changes.'
    }
    $existing = @((Api get 'actions/actions?per_page=100').actions |
        Where-Object name -eq 'ACMP Connect Private Login')
    if ($existing.Count -ne 1) { throw 'Expected one existing private login Action.' }
    $actionId = $existing[0].id
    $current = Api get "actions/actions/$actionId"
    $bindings = Api get 'actions/triggers/post-login/bindings'
    if (!$current.deployed_version -or $actionId -notin $bindings.bindings.action.id) {
        throw 'Existing private Action must already be deployed and bound.'
    }
    $databases = @(Api get 'connections?per_page=100' |
        Where-Object { $_.name -eq 'Username-Password-Authentication' -and $_.strategy -eq 'auth0' })
    if ($databases.Count -ne 1 -or !$databases[0].options.disable_signup) {
        throw 'Expected database connection with signup already disabled.'
    }
    $user = Api get ('users/' + [uri]::EscapeDataString($AllowedUserIds[0]))
    if ($user.blocked -or @($user.identities.connection) -notcontains 'Username-Password-Authentication') {
        throw 'Expected an unblocked user in the private database connection.'
    }
    $secretNames = @($current.secrets.name)
    foreach ($required in @('CHATGPT_CLIENT_ID', 'PORTAL_CLIENT_ID', 'ALLOWED_USER_IDS')) {
        if ($required -notin $secretNames) { throw 'Existing Action secrets are incomplete.' }
    }
    # A name without a value preserves that secret, per the Management API contract.
    $secrets = @($current.secrets | ForEach-Object {
        if ($_.name -eq 'ALLOWED_USER_IDS') {
            @{name=$_.name; value=(ConvertTo-Json -InputObject @($AllowedUserIds) -Compress)}
        } else { @{name=$_.name} }
    })
    $null = Api patch "actions/actions/$actionId" @{secrets=$secrets}
    for ($attempt=0; $attempt -lt 15; $attempt++) {
        $updated = Api get "actions/actions/$actionId"
        if ($updated.status -eq 'built') { break }
        if ($updated.status -eq 'failed') { throw 'Action build failed.' }
        Start-Sleep -Seconds 2
    }
    if ($updated.status -ne 'built') { throw 'Action build timed out.' }
    $deployed = Api post "actions/actions/$actionId/deploy" @{}
    $verified = Api get "actions/actions/$actionId"
    $bindings = Api get 'actions/triggers/post-login/bindings'
    $db = Api get "connections/$($databases[0].id)"
    if (!$verified.deployed_version -or $verified.deployed_version.id -ne $deployed.id -or
        $actionId -notin $bindings.bindings.action.id -or !$db.options.disable_signup -or
        $verified.code -cne $current.code) { throw 'Private Action verification failed.' }
    Write-Output 'Verified: singleton allowlist update accepted, deployed and bound; signup disabled.'
    return
}
if ($Origin) {
    $uri = [uri]$Origin
    if (!$uri.IsAbsoluteUri -or $uri.Scheme -ne 'https' -or $uri.AbsolutePath -ne '/' -or $uri.Query -or $uri.Fragment -or $uri.UserInfo) {
        throw 'Origin must be an actual HTTPS origin, without a path, query or credentials.'
    }
    $Origin = $Origin.TrimEnd('/')
}
if ($ChatGPTCallback -and $ChatGPTCallback -notmatch '^https://chatgpt\.com/(connector/oauth/[A-Za-z0-9_-]+|connector_platform_oauth_redirect)$') {
    throw 'Use the exact callback displayed by ChatGPT; no templates or wildcards.'
}
$settings = Api get 'tenants/settings'
if ($settings.resource_parameter_profile -ne 'compatibility') {
    $null = Api patch 'tenants/settings' @{resource_parameter_profile='compatibility'}
}
$clients = @(Api get 'clients?per_page=100&fields=client_id,name,callbacks&include_fields=true')
$ids = @{}
foreach ($entry in @(
    @{name='ChatGPT MCP'; aliases=@('ChatGPT MCP','ACMP ChatGPT'); key='chatgpt'},
    @{name='ACMP Connect Portal'; aliases=@('ACMP Connect Portal','ACMP Portal'); key='portal'}
)) {
    $matches = @($clients | Where-Object name -in $entry.aliases)
    if ($matches.Count -gt 1) { throw "Ambiguous existing application: $($entry.name)" }
    $body = @{
        name=$entry.name; app_type='regular_web'; is_first_party=$true
        oidc_conformant=$true; token_endpoint_auth_method='client_secret_post'
        grant_types=@('authorization_code')
    }
    if ($entry.key -eq 'chatgpt') {
        $body.grant_types = @('authorization_code','refresh_token')
        $body.refresh_token = @{
            rotation_type='rotating'; expiration_type='expiring'; token_lifetime=2592000
            idle_token_lifetime=604800; infinite_token_lifetime=$false
            infinite_idle_token_lifetime=$false; leeway=3
        }
        if ($ChatGPTCallback) { $body.callbacks = @($ChatGPTCallback) }
    } elseif ($Origin) { $body.callbacks = @("$Origin/connect/callback") }
    if ($matches.Count) {
        $client = Api patch "clients/$($matches[0].client_id)" $body
    } else {
        if (!$body.ContainsKey('callbacks')) { $body.callbacks = @() }
        $client = Api post 'clients' $body
    }
    $ids[$entry.key] = $client.client_id
    Write-Output "$($entry.name): $($client.client_id)"
}
$actions = @( (Api get 'actions/actions?per_page=100').actions | Where-Object name -eq 'ACMP Connect Private Login' )
if ($actions.Count -gt 1) { throw 'Ambiguous existing ACMP Action' }
$secrets = @(
    @{name='CHATGPT_CLIENT_ID'; value=$ids.chatgpt},
    @{name='PORTAL_CLIENT_ID'; value=$ids.portal}
)
if ($PSBoundParameters.ContainsKey('AllowedUserIds') -or !$actions.Count) {
    $secrets += @{name='ALLOWED_USER_IDS'; value=(ConvertTo-Json -InputObject @($AllowedUserIds | Where-Object { $_ }) -Compress)}
}
$actionBody = @{
    name='ACMP Connect Private Login'; runtime='node22'
    supported_triggers=@(@{id='post-login'; version='v3'})
    code=(Get-Content -Raw (Join-Path $PSScriptRoot '../docs/auth0-private-login.js'))
    secrets=$secrets
}
if ($actions.Count -and !$PSBoundParameters.ContainsKey('AllowedUserIds')) {
    # Auth0 does not return secret values. Preserve the existing allowlist on reruns.
    $actionBody.Remove('secrets')
}
if ($actions.Count) { $action = Api patch "actions/actions/$($actions[0].id)" $actionBody }
else { $action = Api post 'actions/actions' $actionBody }
$actionId = $action.id
for ($attempt=0; $attempt -lt 12; $attempt++) {
    $action = Api get "actions/actions/$actionId"
    if ($action.status -eq 'built') { break }
    if ($action.status -eq 'failed') { throw 'Action build failed' }
    Start-Sleep -Seconds 2
}
if ($action.status -ne 'built') { throw 'Action is still building; rerun later' }
$null = Api post "actions/actions/$actionId/deploy" @{}
$bindings = @((Api get 'actions/triggers/post-login/bindings').bindings)
if ($actionId -notin $bindings.action.id) {
    $newBindings = @($bindings | ForEach-Object { @{ref=@{type='action_id'; value=$_.action.id}; display_name=$_.display_name} })
    $newBindings += @{ref=@{type='action_id'; value=$actionId}; display_name='ACMP Connect Private Login'}
    $null = Api patch 'actions/triggers/post-login/bindings' @{bindings=$newBindings}
}
Write-Output "Post Login Action: $actionId"
$connections = @(Api get 'connections?fields=id,name,strategy&include_fields=true&per_page=100')
$database = @($connections | Where-Object { $_.strategy -eq 'auth0' -and $_.name -eq 'Username-Password-Authentication' })
if ($database.Count -ne 1) { throw 'Expected one Username-Password-Authentication connection' }
$db = Api get "connections/$($database[0].id)"
$options = $db.options
$options | Add-Member -NotePropertyName disable_signup -NotePropertyValue $true -Force
$null = Api patch "connections/$($db.id)" @{options=$options}
foreach ($connection in $connections) {
    $enabled = $connection.id -eq $db.id
    $null = Api patch "connections/$($connection.id)/clients" @(
        @{client_id=$ids.chatgpt; status=$enabled},
        @{client_id=$ids.portal; status=$enabled}
    )
}
if ($Origin) {
    $audience = "$Origin/mcp"
    $apis = @(Api get 'resource-servers?per_page=100')
    $matches = @($apis | Where-Object { $_.identifier -eq $audience -or $_.name -eq 'ACMP Connect' })
    if ($matches.Count -gt 1 -or ($matches.Count -and $matches[0].identifier -ne $audience)) {
        throw 'Existing API conflicts with the requested audience; manual review required'
    }
    $apiBody = @{
        name='ACMP Connect'; signing_alg='RS256'; token_lifetime=900; token_lifetime_for_web=900
        allow_offline_access=$true; enforce_policies=$false
        scopes=@(
            @{value='acmp:read'; description='Read ACMP problems and results'},
            @{value='acmp:submit'; description='Submit ACMP solutions'},
            @{value='acmp:manage'; description='Manage the linked ACMP account'}
        )
    }
    if ($matches.Count) { $null = Api patch "resource-servers/$($matches[0].id)" $apiBody }
    else { $apiBody.identifier=$audience; $null = Api post 'resource-servers' $apiBody }
    Write-Output "API audience: $audience"
} else { Write-Output 'API creation pending: actual HTTPS Origin is required.' }
# Re-fetch only public settings for the verification output.
foreach ($id in $ids.Values) {
    Api get "clients/$($id)?fields=client_id,name,app_type,grant_types,callbacks,token_endpoint_auth_method,oidc_conformant,is_first_party,refresh_token&include_fields=true" | ConvertTo-Json -Depth 8
}
$verifiedAction = Api get "actions/actions/$actionId"
if (!$verifiedAction.deployed_version) { throw 'Action has no deployed version' }
$verifiedBindings = Api get 'actions/triggers/post-login/bindings'
if ($actionId -notin $verifiedBindings.bindings.action.id) { throw 'Action is not bound' }
$verifiedDb = Api get "connections/$($db.id)"
if (!$verifiedDb.options.disable_signup) { throw 'Signup was not disabled' }
Write-Output 'Verified: Action deployed and bound; database signup disabled.'
