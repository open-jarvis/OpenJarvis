# On-device acceptance measurements for Surface Laptop Ultra (or any Windows ARM64 host).
# Records cold start, time to first SSE token, tokens/sec, and working-set memory.
[CmdletBinding()]
param(
    [string]$ApiUrl = "http://127.0.0.1:8000",
    [string]$Model = "Phi-4-mini-instruct",
    [string]$Prompt = "Reply with a single short sentence about Windows on ARM."
)

$ErrorActionPreference = "Stop"
$Result = [ordered]@{
    device = $env:COMPUTERNAME
    os = [System.Environment]::OSVersion.VersionString
    arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    model = $Model
    execution_provider = ""
    cpu_fallback = $false
    cold_start_ms = $null
    time_to_first_token_ms = $null
    tokens_per_second = $null
    completion_tokens = $null
    working_set_mb = [ordered]@{}
}

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$deadline = (Get-Date).AddMinutes(10)
do {
    try {
        $health = Invoke-WebRequest -Uri "$ApiUrl/health" -UseBasicParsing -TimeoutSec 2
        if ($health.StatusCode -eq 200) { break }
    } catch {
        Start-Sleep -Milliseconds 500
    }
} while ((Get-Date) -lt $deadline)
$sw.Stop()
$Result.cold_start_ms = [int]$sw.Elapsed.TotalMilliseconds

try {
    $info = Invoke-RestMethod -Uri "$ApiUrl/v1/info"
    $Result.model = $info.model
    $Result.execution_provider = $info.hardware.execution_provider
    $Result.cpu_fallback = [bool]$info.hardware.execution_provider_fallback
} catch {
    Write-Warning "Could not read /v1/info"
}

$body = @{
    model = $Model
    stream = $true
    messages = @(@{ role = "user"; content = $Prompt })
} | ConvertTo-Json
$req = [System.Net.HttpWebRequest]::Create("$ApiUrl/v1/chat/completions")
$req.Method = "POST"
$req.ContentType = "application/json"
$bytes = [Text.Encoding]::UTF8.GetBytes($body)
$req.ContentLength = $bytes.Length
$stream = $req.GetRequestStream()
$stream.Write($bytes, 0, $bytes.Length)
$stream.Close()

$ttft = [System.Diagnostics.Stopwatch]::StartNew()
$first = $null
$usage = $null
$resp = $req.GetResponse()
$reader = New-Object System.IO.StreamReader($resp.GetResponseStream())
while (-not $reader.EndOfStream) {
    $line = $reader.ReadLine()
    if ($line -like "data: *") {
        $data = $line.Substring(6)
        if ($data -eq "[DONE]") { break }
        try {
            $json = $data | ConvertFrom-Json
            if (-not $first -and $json.choices[0].delta.content) {
                $ttft.Stop()
                $first = $json.choices[0].delta.content
                $Result.time_to_first_token_ms = [int]$ttft.Elapsed.TotalMilliseconds
            }
            if ($json.usage.completion_tokens) {
                $usage = $json.usage
            }
        } catch { }
    }
}
$reader.Close()
$resp.Close()

if ($usage) {
    $Result.completion_tokens = $usage.completion_tokens
    if ($Result.time_to_first_token_ms -gt 0) {
        $totalSec = $ttft.Elapsed.TotalSeconds
        if ($totalSec -gt 0) {
            $Result.tokens_per_second = [math]::Round($usage.completion_tokens / $totalSec, 2)
        }
    }
}

foreach ($name in @("OpenJarvis", "python", "jarvis", "foundry")) {
    $procs = Get-Process -Name $name -ErrorAction SilentlyContinue
    if ($procs) {
        $Result.working_set_mb[$name] = [math]::Round(($procs | Measure-Object WorkingSet64 -Sum).Sum / 1MB, 1)
    }
}

$Out = Join-Path $PSScriptRoot "..\..\docs\getting-started\windows-winui-perf-last.json"
$Result | ConvertTo-Json -Depth 6 | Set-Content $Out
$Result | ConvertTo-Json -Depth 6
Write-Host "Wrote $Out - paste the numbers into windows-winui-acceptance.md"
