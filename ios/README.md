# OpenJarvis on iPadOS (a-Shell)

Run the OpenJarvis agent runtime locally on an M-series iPad (iPadOS 26/27+) inside **a-Shell** / **a-Shell mini**, routing inference to Apple Intelligence Foundation Models via a Clipboard Protocol Bridge and the `AskAFM` Apple Shortcut.

All iPadOS-specific files are isolated in `ios/` so upstream OpenJarvis merges stay clean.

## Directory Layout

| Repo File | iPadOS Install Destination | Purpose |
| --- | --- | --- |
| `ios/jarvis_ios.py` | `~/Documents/.jarvis/ios/jarvis_ios.py` | Mocks `zeus_apple_silicon`, `apple_fm_sdk`, and `psutil`, then runs `openjarvis.cli`. |
| `ios/jarvis_server.py` | `~/Documents/.jarvis/ios/jarvis_server.py` | HTTP bridge on `127.0.0.1:8085` (Web UI, `/api/chat`, `/v1/chat/completions`, `/shutdown`). |
| `ios/start_jarvis.sh` | `~/Documents/.jarvis/ios/start_jarvis.sh` | Exports `OPENJARVIS_CONFIG` and starts `jarvis_server.py`. |
| `ios/config.toml` | `~/Library/openjarvis/config.toml` | iPadOS configuration pointing `[engine.apple_fm]` to `http://127.0.0.1:8085`. |
| `ios/install.sh` | *(run from repo)* | Installs files, configures `~/.profile` aliases, and installs `openjarvis` with `--no-deps`. |

## Setup in a-Shell

From the cloned `OpenJarvis` repository root in a-Shell:

```sh
sh ios/install.sh && source ~/.profile
```

This adds the following to `~/.profile`:

```sh
export OPENJARVIS_CONFIG="$HOME/Library/openjarvis/config.toml"
alias jarvis="python3 $HOME/Documents/.jarvis/ios/jarvis_ios.py"
alias start_jarvis="sh $HOME/Documents/.jarvis/ios/start_jarvis.sh"
```

## Apple Shortcut Specification: `AskAFM`

- **Shortcut Name:** `AskAFM`
- **I/O Transport:** System Clipboard (`pbcopy` / `pbpaste`)
- **Request Payload:** `JARVIS_REQ||<MODE>||<UUID>||<PROMPT>` (`MODE` is `LOCAL` or `CLOUD`)
- **Response Payload:** `JARVIS_RES||<UUID>||<RESPONSE>`

### Action Tree

1. **Get Clipboard**
2. **Split Text** (`Clipboard`) by Custom `||`
3. **If** `Split Text` (Item 1) **is** `JARVIS_REQ`:
   1. Set variable `Mode` = Item 2 (`LOCAL` or `CLOUD`)
   2. Set variable `ReqID` = Item 3 (`UUID`)
   3. Set variable `Prompt` = Item 4
   4. **If** `Mode` **is** `CLOUD`:
      - **Use Model** (Apple Intelligence — Private Cloud Compute) with `Prompt`
   5. **Otherwise**:
      - **Use Model** (Apple Intelligence — On-Device) with `Prompt`
   6. **Text**: `JARVIS_RES||[ReqID]||[Model Response]`
   7. **Copy** (`Text`) **to Clipboard**

## Execution

- **Launch Web UI & Bridge (`127.0.0.1:8085`):**
  ```sh
  start_jarvis
  ```
- **CLI Query (On-Device):**
  ```sh
  jarvis ask "Summarize this note"
  ```
- **CLI Query (Cloud PCC):**
  ```sh
  jarvis ask --model AskAFMCloud "Explain quantum computing"
  ```
