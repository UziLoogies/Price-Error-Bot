# Scan Lock Recovery Guide

## Symptoms

- Scheduled scans skip with "Scan already running; skipping scheduled run"
- Manual scans appear to do nothing while a scan is active
- Scan jobs remain in `status="running"` for long periods

## Quick Diagnosis

Run the diagnostic script:

```
python scripts/diagnose_scan_lock.py
```

Review:

- Redis lock presence + TTL
- Heartbeat age (stale if > 300s)
- Any `ScanJob` rows stuck in `running`

## Recovery Steps

1) Stop the bot process

2) Clear stale lock (preferred: API)

- Call admin endpoint:
  - `POST /api/scans/admin/force-unlock`

3) Reset stuck ScanJobs (if any)

Example SQL:

```
UPDATE scan_jobs
SET status = 'failed',
    completed_at = NOW(),
    error_message = 'Recovery: force unlock'
WHERE status = 'running';
```

4) Restart the bot

5) Verify

- Confirm the next scheduled scan proceeds
- Manual "Run Scan Now" queues at most one pending scan

## Notes

- Heartbeat age > 300s indicates stale lock even if TTL is still present.
- Startup includes a self-healing check that clears locks with heartbeat age > 10 minutes.
