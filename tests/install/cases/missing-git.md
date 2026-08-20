# Failure: git missing from PATH

## Trigger

`git` is not installed (e.g., fresh macOS without Xcode CLI tools, minimal Linux container).

## Expected behavior

- Hard fail at prereq probe before any state is created.
- stderr includes platform-specific install hint:
  - macOS: `xcode-select --install`
  - Debian/Ubuntu: `sudo apt install git curl`
  - Fedora/RHEL: `sudo dnf install git curl`
  - Arch: `sudo pacman -S git curl`
- Exit code: non-zero.

## Retry

Install `git` per the printed hint, then re-run the curl line.

## Test

`tests/install/bash/test_install.bats::"fails loudly when git is missing"`
