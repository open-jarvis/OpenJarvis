# Failure: install.sh run as root

## Trigger

User runs `sudo bash install.sh` or invokes the installer from a root shell.

## Expected behavior

- Hard fail before any state is created.
- stderr includes "don't run as root" and a hint to re-run as the regular user.
- Exit code: non-zero.

## Retry

Re-run as the regular user (without sudo):

```bash
curl -fsSL https://openjarvis.ai/install.sh | bash
```

## Test

`tests/install/bash/test_install.bats::"refuses to run as root"`
