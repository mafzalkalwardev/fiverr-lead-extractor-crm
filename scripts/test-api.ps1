# Quick API smoke test (requires npm run dev + MongoDB + Redis 5+ + npm run worker)
$ErrorActionPreference = "Stop"
$base = "http://localhost:3000"
$email = "smoke_$(Get-Date -Format 'yyyyMMddHHmmss')@test.local"
$pass = "TestPass123!"

Write-Host "=== Register ===" -ForegroundColor Cyan
$reg = Invoke-RestMethod -Uri "$base/api/auth/register" -Method POST -ContentType "application/json" -Body (@{
  name = "Smoke Test"; email = $email; password = $pass
} | ConvertTo-Json)
if (-not $reg.token) { throw "Register failed: no token" }
$token = $reg.token
Write-Host "OK - token received"

Write-Host "=== Login ===" -ForegroundColor Cyan
$login = Invoke-RestMethod -Uri "$base/api/auth/login" -Method POST -ContentType "application/json" -Body (@{
  email = $email; password = $pass
} | ConvertTo-Json)
Write-Host "OK"

$headers = @{ Authorization = "Bearer $token" }

Write-Host "=== Start job ===" -ForegroundColor Cyan
$job = Invoke-RestMethod -Uri "$base/api/jobs/start" -Method POST -ContentType "application/json" -Headers $headers -Body (@{
  keyword = "logo design"
  category = "graphics-design"
  maxPages = 1
  maxGigs = 3
  maxReviewsPerGig = 2
  delaySeconds = 1
} | ConvertTo-Json)
$jobId = $job.job._id
Write-Host "OK - job $jobId"

Write-Host "=== Wait 20s for worker ===" -ForegroundColor Cyan
Start-Sleep -Seconds 20

Write-Host "=== Job status ===" -ForegroundColor Cyan
$status = Invoke-RestMethod -Uri "$base/api/jobs/$jobId" -Headers $headers
$j = $status.job
Write-Host "status=$($j.status) gigs=$($j.totalGigsFound) reviews=$($j.totalReviewsExtracted) progress=$($j.progressPercent)%"
if ($j.status -ne "completed") { throw "Job did not complete (status=$($j.status)). Is npm run worker running?" }

Write-Host "=== Excel export ===" -ForegroundColor Cyan
$out = "$env:TEMP\job-$jobId-export.xlsx"
Invoke-WebRequest -Uri "$base/api/jobs/$jobId/export" -Headers $headers -OutFile $out
$size = (Get-Item $out).Length
if ($size -lt 1000) { throw "Export file too small ($size bytes)" }
Write-Host "OK - $size bytes -> $out"

Write-Host "`nAll smoke tests passed." -ForegroundColor Green
