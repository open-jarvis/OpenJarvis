# Phase 8A: vollständige Backup-Policy-Planung

Stand: 31. Juli 2026

## Entscheidung und Grenzen

Dieser Bericht dokumentiert ausschließlich den metadata-only Planungsmodus. Es wurde kein dritter Legacy-Backupversuch gestartet, kein Legacy-Backupziel erzeugt, kein Vault-Dry-Run begonnen und keine Phase-8B-Arbeit ausgeführt.

- Quellenlabel: `legacy-jarvis-desktop`
- Legacy-HEAD: `6a333806d184f7cf65ebad63dfee70cdbdcbddac`
- Legacy-Git-Status-Einträge: 157
- geplantes Ziellabel: `phase-8a-long-external-tree`
- erfasste Pfade: 22793
- Quelle über zwei Metadatenscans stabil: `true`
- Quelldateiinhalte geöffnet oder gehasht: `0`
- Copy- oder Netzwerkaufrufe: `0`

## Vollständige Top-Level-Inventur

| Relativer Pfad | Typ | Kategorie | Entscheidung |
| --- | --- | --- | --- |
| `.git` | directory | `build_artifact_excluded` | `exclude` |
| `.gitattributes` | file | `migration_configuration` | `content_backup` |
| `.gitignore` | file | `migration_configuration` | `content_backup` |
| `.venv` | directory | `build_artifact_excluded` | `exclude` |
| `AGENTS.md` | file | `migration_documentation` | `content_backup` |
| `automations` | directory | `migration_workflow_metadata` | `content_backup` |
| `backend` | directory | `migration_source_code` | `content_backup` |
| `config` | directory | `migration_configuration` | `content_backup` |
| `deployment-backups` | directory | `build_artifact_excluded` | `exclude` |
| `desktop` | directory | `migration_source_code` | `content_backup` |
| `docs` | directory | `migration_documentation` | `content_backup` |
| `evals` | directory | `migration_test` | `content_backup` |
| `frontend` | directory | `migration_source_code` | `content_backup` |
| `node_modules` | directory | `build_artifact_excluded` | `exclude` |
| `package-lock.json` | file | `migration_configuration` | `content_backup` |
| `package.json` | file | `migration_configuration` | `content_backup` |
| `pyproject.toml` | file | `migration_configuration` | `content_backup` |
| `README.md` | file | `migration_documentation` | `content_backup` |
| `scripts` | directory | `migration_source_code` | `content_backup` |
| `skills` | directory | `migration_skill_metadata` | `content_backup` |
| `state` | directory | `runtime_state_metadata_only` | `metadata_only` |
| `tests` | directory | `migration_test` | `content_backup` |
| `training` | directory | `migration_source_code` | `content_backup` |

## Klassifikationsmodell

Jeder erfasste Pfad besitzt genau eine der folgenden Kategorien. Die Policy wird vor jeder Content-Entscheidung angewendet.

| Kategorie | Definition | Root-/Kontextregel | Backup | Lesen | Hashen | Migration | Begründung |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `migration_source_code` | Application and support source code. | backend/, frontend/, desktop/, scripts/, training code, or safe root code. | `content_backup` | true | true | true | Required for selective logic and test review. |
| `migration_test` | Test code and deterministic fixtures. | test/, tests/, evals/, test-named paths inside source roots. | `content_backup` | true | true | true | Candidate for isolated test porting. |
| `migration_documentation` | Documentation without runtime authority. | docs/ or documentation files outside prohibited roots. | `content_backup` | true | true | true | Supports traceable migration decisions. |
| `migration_configuration` | Non-secret static project configuration. | config/ or recognized configuration files after secret checks. | `content_backup` | true | true | true | Configuration can be reviewed but never trusted automatically. |
| `migration_skill_metadata` | Legacy skill definitions treated as untrusted metadata. | skills/ after credential and artifact exclusions. | `content_backup` | true | true | false | Skills require quarantine and explicit later review. |
| `migration_workflow_metadata` | Legacy workflow or automation definitions as metadata. | automations/ or workflows/ after prohibited-data checks. | `content_backup` | true | true | false | Workflows must never become active through backup. |
| `runtime_state_metadata_only` | Runtime state represented only by filesystem metadata. | state/ or runtime/, excluding model/cache/prohibited subtrees. | `metadata_only` | false | false | false | Historical runtime payloads are not trusted migration input. |
| `model_artifact_metadata_only` | Model weights or downloaded model assets represented only by metadata. | state/models/ or model-weight extensions outside a cache subtree. | `metadata_only` | false | false | false | Model binaries are not migration-relevant project content. |
| `technical_cache_excluded` | Generated cache or model-download cache. | Cache names only inside known runtime/model/generated contexts. | `exclude` | false | false | false | Regenerable cache data is excluded without content access. |
| `build_artifact_excluded` | Dependency, VCS, build, or compiler artifact. | .git, .venv, node_modules, build, dist, target, and related roots. | `exclude` | false | false | false | Build and dependency artifacts are not restore inputs. |
| `credential_or_session_prohibited` | Credential, token, cookie, secret, or session material. | Known sensitive file and directory names in any root. | `prohibit` | false | false | false | Credential and session content must not be read or copied. |
| `browser_runtime_prohibited` | Browser profile or browser runtime state. | Known browser-profile and User Data directory names. | `prohibit` | false | false | false | Real browser state and accounts are outside migration scope. |
| `temporary_excluded` | Temporary files, logs, tool output, or generated transient data. | temp/tmp/log roots or transient suffixes in technical contexts. | `exclude` | false | false | false | Transient data has no controlled restore role. |
| `unknown_review_required` | Path without a complete root-based policy decision. | Any root or file purpose not covered by an explicit rule. | `review_required` | false | false | false | Unknown data blocks backup simulation until explicitly classified. |

### Ergebnis nach Kategorie

| Kategorie | Pfade | Dateibytes |
| --- | ---: | ---: |
| `migration_source_code` | 129 | 1213458 |
| `migration_test` | 44 | 226165 |
| `migration_documentation` | 36 | 193210 |
| `migration_configuration` | 23 | 76580 |
| `migration_skill_metadata` | 28 | 45969 |
| `migration_workflow_metadata` | 1 | 0 |
| `runtime_state_metadata_only` | 4017 | 579339811 |
| `model_artifact_metadata_only` | 37 | 693847294 |
| `technical_cache_excluded` | 588 | 271693638 |
| `build_artifact_excluded` | 17847 | 3275740075 |
| `credential_or_session_prohibited` | 7 | 534588 |
| `browser_runtime_prohibited` | 1 | 0 |
| `temporary_excluded` | 35 | 1672960 |
| `unknown_review_required` | 0 | 0 |

## Root-basierte technische Policy

Positive Content-Roots sind `backend`, `desktop`, `frontend`, `scripts`, `src`, `training`, `tests`, `test`, `evals`, `docs`, `config`, `skills`, `automations` und `workflows`. In `src`, `docs`, `test` und `tests` führt ein Name wie `cache`, `*-cache` oder `*_cache` allein niemals zum Ausschluss.

Technische beziehungsweise Runtime-Kontexte sind `state`, `runtime`, `models`, `model-data`, `generated`, `generated-data`, `artifacts` und `var`. Nur innerhalb dieser Kontexte gelten `.cache`, `cache`, `caches`, `review-cache`, `*-cache`, `*_cache`, Hugging-Face-Downloadstrukturen und Piper-Caches als `technical_cache_excluded`.

Build-/Dependency-Roots wie `.git`, `.venv`, `node_modules`, `build`, `dist` und `target` sind `build_artifact_excluded`. Credential-, Session- und Browserprofile haben unabhängig vom Root Vorrang und sind prohibited. Reparse Points werden als `unknown_review_required` erfasst und niemals verfolgt.

## Content-Backup und metadata-only Runtime-Inventar

### A. Migrationsrelevanter Content-Backup

Vorgesehen sind ausschließlich die sechs `migration_*`-Kategorien. Skill- und Workflow-Dateien bleiben untrusted metadata und dürfen durch einen Backup weder registriert noch aktiviert werden.

### B. Metadata-only Runtime-Inventar

`state` und `runtime` werden nicht als normale Projektdateien behandelt. Das Inventar enthält nur relative Pfade, Kategorie, Größe, Erweiterung und Struktur. Inhalte, Hashes, Logs, Tooloutputs, Sessions, Browserdaten und Credentials sind ausgeschlossen.

**Empfehlung:** Der gesamte Root `state/models` bleibt standardmäßig `model_artifact_metadata_only`. Selbst kleine JSON-/YAML-/TOML-Dateien werden nicht still übernommen. Eine spätere Allowlist für einzelne Modellkonfigurationen benötigt eine separate Nutzerentscheidung.

### Runtime-/Modellstruktur auf Ebene 2

| Pfad | Kategorie | Entscheidung |
| --- | --- | --- |
| `state/audio` | `runtime_state_metadata_only` | `metadata_only` |
| `state/audio-test` | `runtime_state_metadata_only` | `metadata_only` |
| `state/browser-profile` | `browser_runtime_prohibited` | `prohibit` |
| `state/file-journal` | `runtime_state_metadata_only` | `metadata_only` |
| `state/logs` | `temporary_excluded` | `exclude` |
| `state/models` | `model_artifact_metadata_only` | `metadata_only` |
| `state/provider-workspace` | `runtime_state_metadata_only` | `metadata_only` |
| `state/video` | `runtime_state_metadata_only` | `metadata_only` |
| `state/vision` | `runtime_state_metadata_only` | `metadata_only` |
| `state/website-staging` | `runtime_state_metadata_only` | `metadata_only` |

### Erweiterungen im Runtime-/Modell-Metadateninventar

| Erweiterung/Typ | Anzahl |
| --- | ---: |
| `no_extension` | 2738 |
| `.json` | 504 |
| `.png` | 64 |
| `.hyb` | 52 |
| `.js` | 45 |
| `.old` | 36 |
| `.log` | 30 |
| `.txt` | 23 |
| `.pb` | 19 |
| `.html` | 13 |
| `.tflite` | 12 |
| `.sqlite` | 11 |
| `.store` | 11 |
| `.wav` | 11 |
| `.ldb` | 10 |
| `.bak` | 8 |
| `.db` | 7 |
| `.onnx` | 6 |
| `.db-journal` | 5 |
| `.metadata` | 5 |
| `.dll` | 4 |
| `.list` | 3 |
| `.tag` | 3 |
| `.bin` | 2 |
| `.dat` | 2 |
| `.pma` | 2 |
| `.0-a82cb2897a8bf9445d68dcc2be05af89ad4b2fda1fddb2952693be7cd5353ad3` | 1 |
| `.32_13429613529854417` | 1 |
| `.32_13429613529858945` | 1 |
| `.32_13429618516092366` | 1 |
| `.32_13429620301242378` | 1 |
| `.32_13429631161661774` | 1 |
| `.32_13429697916226523` | 1 |
| `.4_13429613529858456` | 1 |
| `.4_13429632976807671` | 1 |
| `.4_13429640116919584` | 1 |
| `.4_13429697916013830` | 1 |
| `.4_13429697916201489` | 1 |
| `.4_13429697916205892` | 1 |
| `.4_13429697916218905` | 1 |
| `.4_13429697916222395` | 1 |
| `.4_13429697916241996` | 1 |
| `.4_13429697916246371` | 1 |
| `.4_13429699694129742` | 1 |
| `.4_13429699694299396` | 1 |
| `.4_13429699694304240` | 1 |
| `.4_13429699694308261` | 1 |
| `.4_13429699694311887` | 1 |
| `.baf` | 1 |
| `.baj` | 1 |
| `.bf` | 1 |
| `.binarypb` | 1 |
| `.css` | 1 |
| `.db-wal` | 1 |
| `.ftz` | 1 |
| `.gif` | 1 |
| `.gz` | 1 |
| `.journal` | 1 |
| `.jsonl` | 1 |
| `.markov` | 1 |
| `.md` | 1 |
| `.model` | 1 |
| `.ort` | 1 |
| `.py` | 1 |
| `.pyc` | 1 |
| `.sig` | 1 |
| `.svg` | 1 |
| `.wasm` | 1 |
| `.webm` | 1 |

## Langpfadanalyse

- Sicheres Windows-Ziellimit: 247
- Zielroot-Länge der bestehenden Variante: 116
- Pfade oberhalb des Limits: 291
- davon sicher ausgeschlossen/metadata-only: 291
- davon migrationsrelevant: 0
- davon unbekannt: 0
- maximal geplante Zielpfadlänge: 282
- Pfade bis 20 Zeichen unter dem Limit: 492
- Pfade mit Segmenten ab 80 Zeichen: 1
- maximal zulässige Content-Zielroot-Länge: 187
- kürzester praktisch geplanter Staging-Root: `C:\j8` (5 Zeichen; nur Strategie, nicht erzeugt)

### Alle Pfade oberhalb des Sicherheitslimits

| Relativer Pfad | Typ | Kategorie | Zielpfad | Relativ | Segment | Tiefe | Entscheidung |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `.venv/Lib/site-packages/onnxruntime/quantization/execution_providers/qnn/__pycache__/mixed_precision_overrides_utils.cpython-311.pyc` | file | `build_artifact_excluded` | 254 | 132 | 47 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/DeprecatedKernelCreateInfos.cpython-311.pyc` | file | `build_artifact_excluded` | 259 | 137 | 43 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/DeprecatedNodeIndexAndKernelDefHash.cpython-311.pyc` | file | `build_artifact_excluded` | 267 | 145 | 51 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/DeprecatedSessionState.cpython-311.pyc` | file | `build_artifact_excluded` | 254 | 132 | 38 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/DeprecatedSubGraphSessionState.cpython-311.pyc` | file | `build_artifact_excluded` | 262 | 140 | 46 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/DimensionValueType.cpython-311.pyc` | file | `build_artifact_excluded` | 250 | 128 | 34 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/InferenceSession.cpython-311.pyc` | file | `build_artifact_excluded` | 248 | 126 | 32 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/KernelTypeStrArgsEntry.cpython-311.pyc` | file | `build_artifact_excluded` | 254 | 132 | 38 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/KernelTypeStrResolver.cpython-311.pyc` | file | `build_artifact_excluded` | 253 | 131 | 37 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/NodesToOptimizeIndices.cpython-311.pyc` | file | `build_artifact_excluded` | 254 | 132 | 38 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/OpIdKernelTypeStrArgsEntry.cpython-311.pyc` | file | `build_artifact_excluded` | 258 | 136 | 42 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/ParameterOptimizerState.cpython-311.pyc` | file | `build_artifact_excluded` | 255 | 133 | 39 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/RuntimeOptimizationRecord.cpython-311.pyc` | file | `build_artifact_excluded` | 257 | 135 | 41 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/RuntimeOptimizationRecordContainerEntry.cpython-311.pyc` | file | `build_artifact_excluded` | 271 | 149 | 55 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/RuntimeOptimizations.cpython-311.pyc` | file | `build_artifact_excluded` | 252 | 130 | 36 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/StringStringEntry.cpython-311.pyc` | file | `build_artifact_excluded` | 249 | 127 | 33 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/TensorTypeAndShape.cpython-311.pyc` | file | `build_artifact_excluded` | 250 | 128 | 34 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/pipeline_stable_diffusion.cpython-311.pyc` | file | `build_artifact_excluded` | 248 | 126 | 41 | 9 | `exclude` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/images/topbar_floating_button_maximize.png` | file | `runtime_state_metadata_only` | 248 | 126 | 35 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/0bf6ab7f94a21cdc9c1649f884333ec20f40a544/0612eb74-a003-46b6-b911-6c4fe6e63391` | directory | `runtime_state_metadata_only` | 257 | 135 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/0bf6ab7f94a21cdc9c1649f884333ec20f40a544/0612eb74-a003-46b6-b911-6c4fe6e63391/index` | file | `runtime_state_metadata_only` | 263 | 141 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/0bf6ab7f94a21cdc9c1649f884333ec20f40a544/0612eb74-a003-46b6-b911-6c4fe6e63391/index-dir` | directory | `runtime_state_metadata_only` | 267 | 145 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/0bf6ab7f94a21cdc9c1649f884333ec20f40a544/0612eb74-a003-46b6-b911-6c4fe6e63391/index-dir/the-real-index` | file | `runtime_state_metadata_only` | 282 | 160 | 40 | 9 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/0bf6ab7f94a21cdc9c1649f884333ec20f40a544/2f2a4d00-309f-4cf7-962c-20819dbc08f1` | directory | `runtime_state_metadata_only` | 257 | 135 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/0bf6ab7f94a21cdc9c1649f884333ec20f40a544/2f2a4d00-309f-4cf7-962c-20819dbc08f1/2a2b7cbbc61290b4_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/0bf6ab7f94a21cdc9c1649f884333ec20f40a544/2f2a4d00-309f-4cf7-962c-20819dbc08f1/6ea66fa5b36b4157_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/0bf6ab7f94a21cdc9c1649f884333ec20f40a544/2f2a4d00-309f-4cf7-962c-20819dbc08f1/92172a9e586cee2a_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/0bf6ab7f94a21cdc9c1649f884333ec20f40a544/2f2a4d00-309f-4cf7-962c-20819dbc08f1/e6039a61e4d2a504_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/0bf6ab7f94a21cdc9c1649f884333ec20f40a544/2f2a4d00-309f-4cf7-962c-20819dbc08f1/index` | file | `runtime_state_metadata_only` | 263 | 141 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/0bf6ab7f94a21cdc9c1649f884333ec20f40a544/2f2a4d00-309f-4cf7-962c-20819dbc08f1/index-dir` | directory | `runtime_state_metadata_only` | 267 | 145 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/0bf6ab7f94a21cdc9c1649f884333ec20f40a544/2f2a4d00-309f-4cf7-962c-20819dbc08f1/index-dir/the-real-index` | file | `runtime_state_metadata_only` | 282 | 160 | 40 | 9 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/15b90030-978d-46ad-a147-fa164e2c153f` | directory | `runtime_state_metadata_only` | 257 | 135 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/15b90030-978d-46ad-a147-fa164e2c153f/4e88ec14b07a03de_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/15b90030-978d-46ad-a147-fa164e2c153f/4fc770c639275414_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/15b90030-978d-46ad-a147-fa164e2c153f/index` | file | `runtime_state_metadata_only` | 263 | 141 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/15b90030-978d-46ad-a147-fa164e2c153f/index-dir` | directory | `runtime_state_metadata_only` | 267 | 145 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/15b90030-978d-46ad-a147-fa164e2c153f/index-dir/the-real-index` | file | `runtime_state_metadata_only` | 282 | 160 | 40 | 9 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/20011afd-245e-4b1b-9bd0-67f734ebc71b` | directory | `runtime_state_metadata_only` | 257 | 135 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/20011afd-245e-4b1b-9bd0-67f734ebc71b/7b1b59698c1ba902_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/20011afd-245e-4b1b-9bd0-67f734ebc71b/a284756eeb4f4b64_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/20011afd-245e-4b1b-9bd0-67f734ebc71b/index` | file | `runtime_state_metadata_only` | 263 | 141 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/20011afd-245e-4b1b-9bd0-67f734ebc71b/index-dir` | directory | `runtime_state_metadata_only` | 267 | 145 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/20011afd-245e-4b1b-9bd0-67f734ebc71b/index-dir/the-real-index` | file | `runtime_state_metadata_only` | 282 | 160 | 40 | 9 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df` | directory | `runtime_state_metadata_only` | 257 | 135 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/03d011f756d64a78_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/03d011f756d64a78_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/03f8c964b9458a7d_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/03f8c964b9458a7d_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/040f11e49243b61d_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/051ad36ee67c317b_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/051ad36ee67c317b_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/06dc6521f1185993_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/06dc6521f1185993_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/0a67355f432340b9_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/10321e9873897921_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/10b2310b59aa93a4_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/10b2310b59aa93a4_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/1369005787598e10_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/1369005787598e10_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/13e83bd1c1ab1541_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/153bba9a429a2c40_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/1672900cc71fe9ab_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/1672900cc71fe9ab_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/18031f09388d52ce_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/18031f09388d52ce_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/1a51f1be0a8fdf52_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/1a51f1be0a8fdf52_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/217bbc87393d2e57_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/22d4a57ac4e23ec3_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/2413c6dd073fddea_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/2413c6dd073fddea_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/264b46d61d915def_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/278122a2eb096440_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/278122a2eb096440_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/2a129ff85c6b1559_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/2a129ff85c6b1559_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/2a15b98971354678_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/2a99e21c738e2a0b_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/2b7e672798cda057_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/2b7e672798cda057_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/2bb582fd7577f97e_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/2c53cde658823a94_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/2c53cde658823a94_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/2ccec3ded4220927_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/2e08a9c6ec333021_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/3055e34b33d94a7f_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/321e64ecacb66619_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/348aae4f13c8f553_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/34d467f947acad13_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/355dbbc08337a93b_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/355dbbc08337a93b_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/3742e809c03a504e_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/3742e809c03a504e_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/37dc59fa0fdce3a3_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/383a36fceaa62055_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/3881c13d201c7aa8_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/39c763e560200cda_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/3b03edf631539a03_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/3baf6e1cdce96d35_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/40f7ff36b3ade151_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/40f7ff36b3ade151_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/43c5553ba2e53f3c_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/43c5553ba2e53f3c_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/452e3e3a02bcee70_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/452e3e3a02bcee70_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/468f996694dbb562_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/468f996694dbb562_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/4fce287b5b441d74_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/50ffab1faa8729c9_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/50ffab1faa8729c9_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/53f0a9e501fcc806_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/53f0a9e501fcc806_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/54bfb130d33d0df3_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/54bfb130d33d0df3_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/5524d7e552fd889a_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/5524d7e552fd889a_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/574b540795aeca12_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/5be0ab35b22a843d_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/5be0ab35b22a843d_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/5c14882e51891d25_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/5e44a7f4adb70c29_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/62344765313d86e6_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/62344765313d86e6_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/65f701fc2d3b6d77_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/67f1189172319be9_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/684d84b945108797_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/684d84b945108797_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/6dcb70bdb8fe40a3_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/78bd57ab70227e9f_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/78bd57ab70227e9f_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/79f151d882f08df2_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/7b242180316745f3_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/7c4863577c43b32f_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/7ed93a10144ac834_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/85f220494be669b7_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/85f73dd0b35f337f_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/85f73dd0b35f337f_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/872b7b4f8bfb485b_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/888c3f0851605c09_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/888c3f0851605c09_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/8bfc77f05f6a3cc5_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/8c2129e90010758d_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/8cce886514f2b2ec_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/8fdcb7992c9e741c_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/95fcbb4ef0998598_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/960aaafa77fbb8a0_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/9e8aa4fdf814d5ed_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/9edf5f432f2b01a8_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/9f211eb61c69eef8_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/9f211eb61c69eef8_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/9f97c8dd99a7773d_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/a35caf37911ffc68_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/a3972e9e39b4462d_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/a3972e9e39b4462d_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/a3f3372854123752_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/a3f3372854123752_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/a4eeb911b4b433aa_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/a4f8d2c06f10a58b_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/a674423cfbfd17cb_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/ab317b2503a74d4f_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/ab317b2503a74d4f_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/ab8e5be042409c8f_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/abd57af2fe046e55_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/abd57af2fe046e55_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/b15bd87405c3b242_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/b15bd87405c3b242_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/b1eb612d97acde28_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/b4f84b300748a114_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/b6a609a2a4d72ee3_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/b7cd751a99c70c48_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/b849a2f19789767a_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/b87cf2f2b0511c4c_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/b9dcc9f4c807eeaa_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/bd3f9ee3f2e520bc_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/bd3f9ee3f2e520bc_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/c65e36407de7ae26_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/c65e36407de7ae26_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/c6ee1195f100501c_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/c6ee1195f100501c_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/c71b92ffb846678f_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/c71b92ffb846678f_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/c95d30c9d70f69cd_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/d36fb6390d81f782_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/d36fb6390d81f782_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/d6af3918ca46ca94_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/d8f4d454415e83ad_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/d8f4d454415e83ad_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/db66a72be9e9dd1f_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/db66a72be9e9dd1f_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/dbde16ab26738e46_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/dbde16ab26738e46_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/dc4038e735155772_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/dd1d9f7425e5aefb_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/df9f3044c9ae2e2e_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/e1c889dbbbc0d4c1_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/e1c889dbbbc0d4c1_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/e2e7236ff12b75b9_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/e2e7236ff12b75b9_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/e3c5699b5189de47_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/e3c5699b5189de47_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/e4071f6047faef52_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/e4071f6047faef52_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/e6504c209cb882d7_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/e6c0a08c45e55298_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/e6c0a08c45e55298_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/e7dedc7674095d3f_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/e7dedc7674095d3f_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/ea6f02895a4e3500_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/ed344a77138c223d_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/f0ce427b28da7d25_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/f12d9bd42964b0e9_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/f1b076f89f1cca1b_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/f3cf0105597dc8c7_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/f3cf0105597dc8c7_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/f5c597fa26086218_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/f5c597fa26086218_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/f7a02825bf690a95_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/f91c7c09e6d47e40_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/f91c7c09e6d47e40_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/f96fbbec894d4c53_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/f96fbbec894d4c53_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/faf5f8ea709d46b2_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/faf5f8ea709d46b2_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/ff5222d57552b6c1_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/index` | file | `runtime_state_metadata_only` | 263 | 141 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/index-dir` | directory | `runtime_state_metadata_only` | 267 | 145 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/48f7c7a1-4f2a-4b83-9b4c-e150d74002df/index-dir/the-real-index` | file | `runtime_state_metadata_only` | 282 | 160 | 40 | 9 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/85d2bd1d-e37b-47fe-bc24-95f96f7153d7` | directory | `runtime_state_metadata_only` | 257 | 135 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/85d2bd1d-e37b-47fe-bc24-95f96f7153d7/233b4113a77b7cd2_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/85d2bd1d-e37b-47fe-bc24-95f96f7153d7/index` | file | `runtime_state_metadata_only` | 263 | 141 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/85d2bd1d-e37b-47fe-bc24-95f96f7153d7/index-dir` | directory | `runtime_state_metadata_only` | 267 | 145 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/85d2bd1d-e37b-47fe-bc24-95f96f7153d7/index-dir/the-real-index` | file | `runtime_state_metadata_only` | 282 | 160 | 40 | 9 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/4cc699dd486af2551d01b1a74abd5337c6e052e5/28ce5dea-0a5a-4f18-a0f4-a2bfd54b2e8e` | directory | `runtime_state_metadata_only` | 257 | 135 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/4cc699dd486af2551d01b1a74abd5337c6e052e5/28ce5dea-0a5a-4f18-a0f4-a2bfd54b2e8e/368793f7111a075f_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/4cc699dd486af2551d01b1a74abd5337c6e052e5/28ce5dea-0a5a-4f18-a0f4-a2bfd54b2e8e/368793f7111a075f_1` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/4cc699dd486af2551d01b1a74abd5337c6e052e5/28ce5dea-0a5a-4f18-a0f4-a2bfd54b2e8e/index` | file | `runtime_state_metadata_only` | 263 | 141 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/4cc699dd486af2551d01b1a74abd5337c6e052e5/28ce5dea-0a5a-4f18-a0f4-a2bfd54b2e8e/index-dir` | directory | `runtime_state_metadata_only` | 267 | 145 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/4cc699dd486af2551d01b1a74abd5337c6e052e5/28ce5dea-0a5a-4f18-a0f4-a2bfd54b2e8e/index-dir/the-real-index` | file | `runtime_state_metadata_only` | 282 | 160 | 40 | 9 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/4cc699dd486af2551d01b1a74abd5337c6e052e5/2e370d43-4a31-43f3-a830-753d26d85204` | directory | `runtime_state_metadata_only` | 257 | 135 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/4cc699dd486af2551d01b1a74abd5337c6e052e5/2e370d43-4a31-43f3-a830-753d26d85204/b82aaf592933a8c9_0` | file | `runtime_state_metadata_only` | 276 | 154 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/4cc699dd486af2551d01b1a74abd5337c6e052e5/2e370d43-4a31-43f3-a830-753d26d85204/index` | file | `runtime_state_metadata_only` | 263 | 141 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/4cc699dd486af2551d01b1a74abd5337c6e052e5/2e370d43-4a31-43f3-a830-753d26d85204/index-dir` | directory | `runtime_state_metadata_only` | 267 | 145 | 40 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/4cc699dd486af2551d01b1a74abd5337c6e052e5/2e370d43-4a31-43f3-a830-753d26d85204/index-dir/the-real-index` | file | `runtime_state_metadata_only` | 282 | 160 | 40 | 9 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Shared Dictionary/cache/index-dir/the-real-index` | file | `technical_cache_excluded` | 249 | 127 | 32 | 11 | `exclude` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Shared Dictionary/cache/index-dir/the-real-index` | file | `technical_cache_excluded` | 249 | 127 | 32 | 11 | `exclude` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/aghbiahbpaijignceidepookljebhfak/Trusted Icons/Icons Maskable` | directory | `runtime_state_metadata_only` | 249 | 127 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/aghbiahbpaijignceidepookljebhfak/Trusted Icons/Icons Monochrome` | directory | `runtime_state_metadata_only` | 251 | 129 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/aghbiahbpaijignceidepookljebhfak/Trusted Icons/Icons/192.png` | file | `runtime_state_metadata_only` | 248 | 126 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/agimnkijcaahngcdmfeangaknmldooml/Trusted Icons/Icons Maskable` | directory | `runtime_state_metadata_only` | 249 | 127 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/agimnkijcaahngcdmfeangaknmldooml/Trusted Icons/Icons Monochrome` | directory | `runtime_state_metadata_only` | 251 | 129 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/agimnkijcaahngcdmfeangaknmldooml/Trusted Icons/Icons/192.png` | file | `runtime_state_metadata_only` | 248 | 126 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fhihpiojkbmbpdjeoajapmgkhlnakfjf/Trusted Icons/Icons Maskable` | directory | `runtime_state_metadata_only` | 249 | 127 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fhihpiojkbmbpdjeoajapmgkhlnakfjf/Trusted Icons/Icons Monochrome` | directory | `runtime_state_metadata_only` | 251 | 129 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fhihpiojkbmbpdjeoajapmgkhlnakfjf/Trusted Icons/Icons/192.png` | file | `runtime_state_metadata_only` | 248 | 126 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fmgjjmmmlfnkbppncabfkddbjimcfncm/Trusted Icons/Icons Maskable` | directory | `runtime_state_metadata_only` | 249 | 127 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fmgjjmmmlfnkbppncabfkddbjimcfncm/Trusted Icons/Icons Monochrome` | directory | `runtime_state_metadata_only` | 251 | 129 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fmgjjmmmlfnkbppncabfkddbjimcfncm/Trusted Icons/Icons/192.png` | file | `runtime_state_metadata_only` | 248 | 126 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/kefjledonklijopmnomlcbpllchaibag/Trusted Icons/Icons Maskable` | directory | `runtime_state_metadata_only` | 249 | 127 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/kefjledonklijopmnomlcbpllchaibag/Trusted Icons/Icons Monochrome` | directory | `runtime_state_metadata_only` | 251 | 129 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/kefjledonklijopmnomlcbpllchaibag/Trusted Icons/Icons/192.png` | file | `runtime_state_metadata_only` | 248 | 126 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/mpnpojknpmmopombnjdcgaaiekajbnjb/Trusted Icons/Icons Maskable` | directory | `runtime_state_metadata_only` | 249 | 127 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/mpnpojknpmmopombnjdcgaaiekajbnjb/Trusted Icons/Icons Monochrome` | directory | `runtime_state_metadata_only` | 251 | 129 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/mpnpojknpmmopombnjdcgaaiekajbnjb/Trusted Icons/Icons/192.png` | file | `runtime_state_metadata_only` | 248 | 126 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/pommaclcbfghclhalboakcipcmmndhcj/Trusted Icons/Icons Maskable` | directory | `runtime_state_metadata_only` | 249 | 127 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/pommaclcbfghclhalboakcipcmmndhcj/Trusted Icons/Icons Monochrome` | directory | `runtime_state_metadata_only` | 251 | 129 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/pommaclcbfghclhalboakcipcmmndhcj/Trusted Icons/Icons/192.png` | file | `runtime_state_metadata_only` | 248 | 126 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/3.0.0-HeuristicClassifierOptimization/metadata.json` | file | `runtime_state_metadata_only` | 248 | 126 | 37 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/2.0.0-DeepEEEnUsProductByRegexOnly/asset` | file | `runtime_state_metadata_only` | 249 | 127 | 34 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/2.0.0-DeepEEEnUsProductByRegexOnly/metadata.json` | file | `runtime_state_metadata_only` | 257 | 135 | 34 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-DeepEEEnUsProductByRegexOnly/asset` | file | `runtime_state_metadata_only` | 249 | 127 | 34 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-DeepEEEnUsProductByRegexOnly/metadata.json` | file | `runtime_state_metadata_only` | 257 | 135 | 34 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-DeepEEEnUsRegexOnly/metadata.json` | file | `runtime_state_metadata_only` | 248 | 126 | 25 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-DeepEEUrlCategoryRegex/metadata.json` | file | `runtime_state_metadata_only` | 251 | 129 | 28 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-DeepEEUrlCategoryRegexCustom/asset` | file | `runtime_state_metadata_only` | 249 | 127 | 34 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-DeepEEUrlCategoryRegexCustom/metadata.json` | file | `runtime_state_metadata_only` | 257 | 135 | 34 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-HeuristicClassifierOptimization/asset` | file | `runtime_state_metadata_only` | 252 | 130 | 37 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-HeuristicClassifierOptimization/metadata.json` | file | `runtime_state_metadata_only` | 260 | 138 | 37 | 8 | `metadata_only` |
| `state/browser-profile/SmartScreen/RemoteData/edgeSettings_2.0-a82cb2897a8bf9445d68dcc2be05af89ad4b2fda1fddb2952693be7cd5353ad3` | file | `runtime_state_metadata_only` | 248 | 126 | 81 | 5 | `metadata_only` |
| `state/models/piper/.cache/huggingface/download/de/de_DE/thorsten_emotional/medium/de_DE-thorsten_emotional-medium.onnx.json.metadata` | file | `technical_cache_excluded` | 254 | 132 | 50 | 11 | `exclude` |
| `state/models/piper/.cache/huggingface/download/de/de_DE/thorsten_emotional/medium/de_DE-thorsten_emotional-medium.onnx.metadata` | file | `technical_cache_excluded` | 249 | 127 | 45 | 11 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE/eva_k/x_low` | directory | `technical_cache_excluded` | 249 | 127 | 40 | 10 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE/eva_k/x_low/MODEL_CARD` | file | `technical_cache_excluded` | 260 | 138 | 40 | 11 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE/kerstin/low` | directory | `technical_cache_excluded` | 249 | 127 | 40 | 10 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE/kerstin/low/MODEL_CARD` | file | `technical_cache_excluded` | 260 | 138 | 40 | 11 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE/mls/medium` | directory | `technical_cache_excluded` | 248 | 126 | 40 | 10 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE/mls/medium/MODEL_CARD` | file | `technical_cache_excluded` | 259 | 137 | 40 | 11 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE/thorsten/high` | directory | `technical_cache_excluded` | 251 | 129 | 40 | 10 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE/thorsten/high/MODEL_CARD` | file | `technical_cache_excluded` | 262 | 140 | 40 | 11 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE/thorsten_emotional` | directory | `technical_cache_excluded` | 256 | 134 | 40 | 9 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE/thorsten_emotional/medium` | directory | `technical_cache_excluded` | 263 | 141 | 40 | 10 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE/thorsten_emotional/medium/MODEL_CARD` | file | `technical_cache_excluded` | 274 | 152 | 40 | 11 | `exclude` |

### Alle Pfade bis 20 Zeichen unter dem Limit

| Relativer Pfad | Typ | Kategorie | Zielpfad | Relativ | Segment | Tiefe | Entscheidung |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `.venv/Lib/site-packages/comtypes/gen/__pycache__/_00020430_0000_0000_C000_000000000046_0_2_0.cpython-311.pyc` | file | `build_artifact_excluded` | 230 | 108 | 59 | 7 | `exclude` |
| `.venv/Lib/site-packages/comtypes/gen/__pycache__/_944DE083_8FB8_45CF_BCB7_C477ACB2F897_0_1_0.cpython-311.pyc` | file | `build_artifact_excluded` | 230 | 108 | 59 | 7 | `exclude` |
| `.venv/Lib/site-packages/comtypes/gen/__pycache__/_C866CA3A_32F7_11D2_9602_00C04F8EE628_0_5_4.cpython-311.pyc` | file | `build_artifact_excluded` | 230 | 108 | 59 | 7 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/audio_classification.cpython-311.pyc` | file | `build_artifact_excluded` | 237 | 115 | 36 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/audio_to_audio.cpython-311.pyc` | file | `build_artifact_excluded` | 231 | 109 | 30 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/automatic_speech_recognition.cpython-311.pyc` | file | `build_artifact_excluded` | 245 | 123 | 44 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/chat_completion.cpython-311.pyc` | file | `build_artifact_excluded` | 232 | 110 | 31 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/depth_estimation.cpython-311.pyc` | file | `build_artifact_excluded` | 233 | 111 | 32 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/document_question_answering.cpython-311.pyc` | file | `build_artifact_excluded` | 244 | 122 | 43 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/feature_extraction.cpython-311.pyc` | file | `build_artifact_excluded` | 235 | 113 | 34 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/image_classification.cpython-311.pyc` | file | `build_artifact_excluded` | 237 | 115 | 36 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/image_segmentation.cpython-311.pyc` | file | `build_artifact_excluded` | 235 | 113 | 34 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/image_text_to_image.cpython-311.pyc` | file | `build_artifact_excluded` | 236 | 114 | 35 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/image_text_to_video.cpython-311.pyc` | file | `build_artifact_excluded` | 236 | 114 | 35 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/image_to_image.cpython-311.pyc` | file | `build_artifact_excluded` | 231 | 109 | 30 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/image_to_text.cpython-311.pyc` | file | `build_artifact_excluded` | 230 | 108 | 29 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/image_to_video.cpython-311.pyc` | file | `build_artifact_excluded` | 231 | 109 | 30 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/object_detection.cpython-311.pyc` | file | `build_artifact_excluded` | 233 | 111 | 32 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/question_answering.cpython-311.pyc` | file | `build_artifact_excluded` | 235 | 113 | 34 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/sentence_similarity.cpython-311.pyc` | file | `build_artifact_excluded` | 236 | 114 | 35 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/summarization.cpython-311.pyc` | file | `build_artifact_excluded` | 230 | 108 | 29 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/table_question_answering.cpython-311.pyc` | file | `build_artifact_excluded` | 241 | 119 | 40 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/text2text_generation.cpython-311.pyc` | file | `build_artifact_excluded` | 237 | 115 | 36 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/text_classification.cpython-311.pyc` | file | `build_artifact_excluded` | 236 | 114 | 35 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/text_generation.cpython-311.pyc` | file | `build_artifact_excluded` | 232 | 110 | 31 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/text_to_audio.cpython-311.pyc` | file | `build_artifact_excluded` | 230 | 108 | 29 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/text_to_image.cpython-311.pyc` | file | `build_artifact_excluded` | 230 | 108 | 29 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/text_to_speech.cpython-311.pyc` | file | `build_artifact_excluded` | 231 | 109 | 30 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/text_to_video.cpython-311.pyc` | file | `build_artifact_excluded` | 230 | 108 | 29 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/token_classification.cpython-311.pyc` | file | `build_artifact_excluded` | 237 | 115 | 36 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/translation.cpython-311.pyc` | file | `build_artifact_excluded` | 228 | 106 | 27 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/video_classification.cpython-311.pyc` | file | `build_artifact_excluded` | 237 | 115 | 36 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/visual_question_answering.cpython-311.pyc` | file | `build_artifact_excluded` | 242 | 120 | 41 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/zero_shot_classification.cpython-311.pyc` | file | `build_artifact_excluded` | 241 | 119 | 40 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/zero_shot_image_classification.cpython-311.pyc` | file | `build_artifact_excluded` | 247 | 125 | 46 | 9 | `exclude` |
| `.venv/Lib/site-packages/huggingface_hub/inference/_generated/types/__pycache__/zero_shot_object_detection.cpython-311.pyc` | file | `build_artifact_excluded` | 243 | 121 | 42 | 9 | `exclude` |
| `.venv/Lib/site-packages/joblib/test/data/joblib_0.9.4.dev0_compressed_cache_size_pickle_py35_np19.gz_01.npy.z` | file | `build_artifact_excluded` | 231 | 109 | 68 | 7 | `exclude` |
| `.venv/Lib/site-packages/joblib/test/data/joblib_0.9.4.dev0_compressed_cache_size_pickle_py35_np19.gz_02.npy.z` | file | `build_artifact_excluded` | 231 | 109 | 68 | 7 | `exclude` |
| `.venv/Lib/site-packages/joblib/test/data/joblib_0.9.4.dev0_compressed_cache_size_pickle_py35_np19.gz_03.npy.z` | file | `build_artifact_excluded` | 231 | 109 | 68 | 7 | `exclude` |
| `.venv/Lib/site-packages/lxml/isoschematron/resources/xsl/iso-schematron-xslt1/iso_schematron_skeleton_for_xslt1.xsl` | file | `build_artifact_excluded` | 237 | 115 | 37 | 9 | `exclude` |
| `.venv/Lib/site-packages/numpy/random/tests/__pycache__/test_generator_mt19937_regressions.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 50 | 8 | `exclude` |
| `.venv/Lib/site-packages/numpy/typing/tests/data/pass/__pycache__/ndarray_shape_manipulation.cpython-311.pyc` | file | `build_artifact_excluded` | 229 | 107 | 42 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/quantization/CalTableFlatBuffers/__pycache__/__init__.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 24 | 8 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/quantization/CalTableFlatBuffers/__pycache__/KeyValue.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 24 | 8 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/quantization/CalTableFlatBuffers/__pycache__/TrtTable.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 24 | 8 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/quantization/execution_providers/qnn/__pycache__/__init__.cpython-311.pyc` | file | `build_artifact_excluded` | 231 | 109 | 24 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/quantization/execution_providers/qnn/__pycache__/fusion_lpnorm.cpython-311.pyc` | file | `build_artifact_excluded` | 236 | 114 | 29 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/quantization/execution_providers/qnn/__pycache__/fusion_spacetodepth.cpython-311.pyc` | file | `build_artifact_excluded` | 242 | 120 | 35 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/quantization/execution_providers/qnn/__pycache__/preprocess.cpython-311.pyc` | file | `build_artifact_excluded` | 233 | 111 | 26 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/quantization/execution_providers/qnn/__pycache__/quant_config.cpython-311.pyc` | file | `build_artifact_excluded` | 235 | 113 | 28 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/quantization/execution_providers/qnn/mixed_precision_overrides_utils.py` | file | `build_artifact_excluded` | 229 | 107 | 34 | 8 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/quantization/fusions/__pycache__/replace_upsample_with_resize.cpython-311.pyc` | file | `build_artifact_excluded` | 235 | 113 | 44 | 8 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/quantization/neural_compressor/__pycache__/onnx_model.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 26 | 8 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/quantization/neural_compressor/__pycache__/weight_only.cpython-311.pyc` | file | `build_artifact_excluded` | 228 | 106 | 27 | 8 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/__pycache__/operator_type_usage_processors.cpython-311.pyc` | file | `build_artifact_excluded` | 239 | 117 | 46 | 8 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/__pycache__/ort_model_processor.cpython-311.pyc` | file | `build_artifact_excluded` | 228 | 106 | 35 | 8 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/__pycache__/__init__.cpython-311.pyc` | file | `build_artifact_excluded` | 236 | 114 | 24 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/__init__.cpython-311.pyc` | file | `build_artifact_excluded` | 240 | 118 | 24 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/ArgType.cpython-311.pyc` | file | `build_artifact_excluded` | 239 | 117 | 23 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/ArgTypeAndIndex.cpython-311.pyc` | file | `build_artifact_excluded` | 247 | 125 | 31 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/Attribute.cpython-311.pyc` | file | `build_artifact_excluded` | 241 | 119 | 25 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/AttributeType.cpython-311.pyc` | file | `build_artifact_excluded` | 245 | 123 | 29 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/Checkpoint.cpython-311.pyc` | file | `build_artifact_excluded` | 242 | 120 | 26 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/Dimension.cpython-311.pyc` | file | `build_artifact_excluded` | 241 | 119 | 25 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/DimensionValue.cpython-311.pyc` | file | `build_artifact_excluded` | 246 | 124 | 30 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/EdgeEnd.cpython-311.pyc` | file | `build_artifact_excluded` | 239 | 117 | 23 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/FloatProperty.cpython-311.pyc` | file | `build_artifact_excluded` | 245 | 123 | 29 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/Graph.cpython-311.pyc` | file | `build_artifact_excluded` | 237 | 115 | 21 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/IntProperty.cpython-311.pyc` | file | `build_artifact_excluded` | 243 | 121 | 27 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/MapType.cpython-311.pyc` | file | `build_artifact_excluded` | 239 | 117 | 23 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/Model.cpython-311.pyc` | file | `build_artifact_excluded` | 237 | 115 | 21 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/ModuleState.cpython-311.pyc` | file | `build_artifact_excluded` | 243 | 121 | 27 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/Node.cpython-311.pyc` | file | `build_artifact_excluded` | 236 | 114 | 20 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/NodeEdge.cpython-311.pyc` | file | `build_artifact_excluded` | 240 | 118 | 24 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/NodeType.cpython-311.pyc` | file | `build_artifact_excluded` | 240 | 118 | 24 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/OperatorSetId.cpython-311.pyc` | file | `build_artifact_excluded` | 245 | 123 | 29 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/OptimizerGroup.cpython-311.pyc` | file | `build_artifact_excluded` | 246 | 124 | 30 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/PropertyBag.cpython-311.pyc` | file | `build_artifact_excluded` | 243 | 121 | 27 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/SequenceType.cpython-311.pyc` | file | `build_artifact_excluded` | 244 | 122 | 28 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/Shape.cpython-311.pyc` | file | `build_artifact_excluded` | 237 | 115 | 21 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/SparseTensor.cpython-311.pyc` | file | `build_artifact_excluded` | 244 | 122 | 28 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/StringProperty.cpython-311.pyc` | file | `build_artifact_excluded` | 246 | 124 | 30 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/Tensor.cpython-311.pyc` | file | `build_artifact_excluded` | 238 | 116 | 22 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/TensorDataType.cpython-311.pyc` | file | `build_artifact_excluded` | 246 | 124 | 30 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/TypeInfo.cpython-311.pyc` | file | `build_artifact_excluded` | 240 | 118 | 24 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/TypeInfoValue.cpython-311.pyc` | file | `build_artifact_excluded` | 245 | 123 | 29 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/__pycache__/ValueInfo.cpython-311.pyc` | file | `build_artifact_excluded` | 241 | 119 | 25 | 10 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/DeprecatedKernelCreateInfos.py` | file | `build_artifact_excluded` | 234 | 112 | 30 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/DeprecatedNodeIndexAndKernelDefHash.py` | file | `build_artifact_excluded` | 242 | 120 | 38 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/DeprecatedSessionState.py` | file | `build_artifact_excluded` | 229 | 107 | 25 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/DeprecatedSubGraphSessionState.py` | file | `build_artifact_excluded` | 237 | 115 | 33 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/KernelTypeStrArgsEntry.py` | file | `build_artifact_excluded` | 229 | 107 | 25 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/KernelTypeStrResolver.py` | file | `build_artifact_excluded` | 228 | 106 | 24 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/NodesToOptimizeIndices.py` | file | `build_artifact_excluded` | 229 | 107 | 25 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/OpIdKernelTypeStrArgsEntry.py` | file | `build_artifact_excluded` | 233 | 111 | 29 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/ParameterOptimizerState.py` | file | `build_artifact_excluded` | 230 | 108 | 26 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/RuntimeOptimizationRecord.py` | file | `build_artifact_excluded` | 232 | 110 | 28 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/RuntimeOptimizationRecordContainerEntry.py` | file | `build_artifact_excluded` | 246 | 124 | 42 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/tools/ort_format_model/ort_flatbuffers_py/fbs/RuntimeOptimizations.py` | file | `build_artifact_excluded` | 227 | 105 | 23 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/__pycache__/convert_tf_models_to_pytorch.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 44 | 7 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/__pycache__/fusion_gpt_attention_megatron.cpython-311.pyc` | file | `build_artifact_excluded` | 228 | 106 | 45 | 7 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/__pycache__/fusion_gpt_attention_no_past.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 44 | 7 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/gpt2/__pycache__/parity_check_helper.cpython-311.pyc` | file | `build_artifact_excluded` | 230 | 108 | 35 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/llama/__pycache__/convert_to_onnx.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 31 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/llama/__pycache__/quant_kv_dataloader.cpython-311.pyc` | file | `build_artifact_excluded` | 231 | 109 | 35 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/longformer/__pycache__/benchmark_longformer.cpython-311.pyc` | file | `build_artifact_excluded` | 237 | 115 | 36 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/longformer/__pycache__/convert_to_onnx.cpython-311.pyc` | file | `build_artifact_excluded` | 232 | 110 | 31 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/longformer/__pycache__/generate_test_data.cpython-311.pyc` | file | `build_artifact_excluded` | 235 | 113 | 34 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/longformer/__pycache__/longformer_helper.cpython-311.pyc` | file | `build_artifact_excluded` | 234 | 112 | 33 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/phi2/__pycache__/inference_example.cpython-311.pyc` | file | `build_artifact_excluded` | 228 | 106 | 33 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/sam2/__pycache__/sam2_image_onnx_predictor.cpython-311.pyc` | file | `build_artifact_excluded` | 236 | 114 | 41 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/__init__.cpython-311.pyc` | file | `build_artifact_excluded` | 231 | 109 | 24 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/benchmark.cpython-311.pyc` | file | `build_artifact_excluded` | 232 | 110 | 25 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/benchmark_controlnet.cpython-311.pyc` | file | `build_artifact_excluded` | 243 | 121 | 36 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/demo_txt2img.cpython-311.pyc` | file | `build_artifact_excluded` | 235 | 113 | 28 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/demo_txt2img_xl.cpython-311.pyc` | file | `build_artifact_excluded` | 238 | 116 | 31 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/demo_utils.cpython-311.pyc` | file | `build_artifact_excluded` | 233 | 111 | 26 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/diffusion_models.cpython-311.pyc` | file | `build_artifact_excluded` | 239 | 117 | 32 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/diffusion_schedulers.cpython-311.pyc` | file | `build_artifact_excluded` | 243 | 121 | 36 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/engine_builder.cpython-311.pyc` | file | `build_artifact_excluded` | 237 | 115 | 30 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/engine_builder_ort_cuda.cpython-311.pyc` | file | `build_artifact_excluded` | 246 | 124 | 39 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/engine_builder_ort_trt.cpython-311.pyc` | file | `build_artifact_excluded` | 245 | 123 | 38 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/engine_builder_tensorrt.cpython-311.pyc` | file | `build_artifact_excluded` | 246 | 124 | 39 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/engine_builder_torch.cpython-311.pyc` | file | `build_artifact_excluded` | 243 | 121 | 36 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/optimize_pipeline.cpython-311.pyc` | file | `build_artifact_excluded` | 240 | 118 | 33 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/ort_optimizer.cpython-311.pyc` | file | `build_artifact_excluded` | 236 | 114 | 29 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/stable_diffusion/__pycache__/trt_utilities.cpython-311.pyc` | file | `build_artifact_excluded` | 236 | 114 | 29 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/t5/__pycache__/t5_encoder_decoder_init.cpython-311.pyc` | file | `build_artifact_excluded` | 232 | 110 | 39 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/whisper/__pycache__/benchmark_all.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 29 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/whisper/__pycache__/convert_to_onnx.cpython-311.pyc` | file | `build_artifact_excluded` | 229 | 107 | 31 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/whisper/__pycache__/whisper_chain.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 29 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/whisper/__pycache__/whisper_decoder.cpython-311.pyc` | file | `build_artifact_excluded` | 229 | 107 | 31 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/whisper/__pycache__/whisper_encoder.cpython-311.pyc` | file | `build_artifact_excluded` | 229 | 107 | 31 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/whisper/__pycache__/whisper_encoder_decoder_init.cpython-311.pyc` | file | `build_artifact_excluded` | 242 | 120 | 44 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/whisper/__pycache__/whisper_helper.cpython-311.pyc` | file | `build_artifact_excluded` | 228 | 106 | 30 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/whisper/__pycache__/whisper_inputs.cpython-311.pyc` | file | `build_artifact_excluded` | 228 | 106 | 30 | 9 | `exclude` |
| `.venv/Lib/site-packages/onnxruntime/transformers/models/whisper/__pycache__/whisper_jump_times.cpython-311.pyc` | file | `build_artifact_excluded` | 232 | 110 | 34 | 9 | `exclude` |
| `.venv/Lib/site-packages/pypdf/_text_extraction/_layout_mode/__pycache__/_fixed_width_page.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 33 | 8 | `exclude` |
| `.venv/Lib/site-packages/pypdf/_text_extraction/_layout_mode/__pycache__/_text_state_manager.cpython-311.pyc` | file | `build_artifact_excluded` | 229 | 107 | 35 | 8 | `exclude` |
| `.venv/Lib/site-packages/pypdf/_text_extraction/_layout_mode/__pycache__/_text_state_params.cpython-311.pyc` | file | `build_artifact_excluded` | 228 | 106 | 34 | 8 | `exclude` |
| `.venv/Lib/site-packages/pypdfium2-5.12.1.dist-info/licenses/data/windows_x64/BUILD_LICENSES/fast_float.txt` | file | `build_artifact_excluded` | 228 | 106 | 26 | 9 | `exclude` |
| `.venv/Lib/site-packages/pypdfium2-5.12.1.dist-info/licenses/data/windows_x64/BUILD_LICENSES/libjpeg_turbo.ijg` | file | `build_artifact_excluded` | 231 | 109 | 26 | 9 | `exclude` |
| `.venv/Lib/site-packages/pypdfium2-5.12.1.dist-info/licenses/data/windows_x64/BUILD_LICENSES/libjpeg_turbo.md` | file | `build_artifact_excluded` | 230 | 108 | 26 | 9 | `exclude` |
| `.venv/Lib/site-packages/pypdfium2-5.12.1.dist-info/licenses/data/windows_x64/BUILD_LICENSES/libopenjpeg.txt` | file | `build_artifact_excluded` | 229 | 107 | 26 | 9 | `exclude` |
| `.venv/Lib/site-packages/pypdfium2-5.12.1.dist-info/licenses/data/windows_x64/BUILD_LICENSES/llvm-libc.txt` | file | `build_artifact_excluded` | 227 | 105 | 26 | 9 | `exclude` |
| `.venv/Lib/site-packages/pypdfium2-5.12.1.dist-info/licenses/data/windows_x64/BUILD_LICENSES/pdfium-binaries.txt` | file | `build_artifact_excluded` | 233 | 111 | 26 | 9 | `exclude` |
| `.venv/Lib/site-packages/scipy/optimize/_trustregion_constr/__pycache__/canonical_constraint.cpython-311.pyc` | file | `build_artifact_excluded` | 229 | 107 | 36 | 8 | `exclude` |
| `.venv/Lib/site-packages/scipy/optimize/_trustregion_constr/__pycache__/equality_constrained_sqp.cpython-311.pyc` | file | `build_artifact_excluded` | 233 | 111 | 40 | 8 | `exclude` |
| `.venv/Lib/site-packages/scipy/optimize/_trustregion_constr/__pycache__/minimize_trustregion_constr.cpython-311.pyc` | file | `build_artifact_excluded` | 236 | 114 | 43 | 8 | `exclude` |
| `.venv/Lib/site-packages/scipy/optimize/_trustregion_constr/tests/__pycache__/test_canonical_constraint.cpython-311.pyc` | file | `build_artifact_excluded` | 240 | 118 | 41 | 9 | `exclude` |
| `.venv/Lib/site-packages/scipy/optimize/_trustregion_constr/tests/__pycache__/test_nested_minimize.cpython-311.pyc` | file | `build_artifact_excluded` | 235 | 113 | 36 | 9 | `exclude` |
| `.venv/Lib/site-packages/scipy/optimize/_trustregion_constr/tests/__pycache__/test_projections.cpython-311.pyc` | file | `build_artifact_excluded` | 231 | 109 | 32 | 9 | `exclude` |
| `.venv/Lib/site-packages/scipy/optimize/_trustregion_constr/tests/__pycache__/test_qp_subproblem.cpython-311.pyc` | file | `build_artifact_excluded` | 233 | 111 | 34 | 9 | `exclude` |
| `.venv/Lib/site-packages/scipy/special/tests/__pycache__/test_support_alternative_backends.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 49 | 8 | `exclude` |
| `.venv/Lib/site-packages/setuptools/config/_validate_pyproject/__pycache__/error_reporting.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 31 | 8 | `exclude` |
| `.venv/Lib/site-packages/setuptools/config/_validate_pyproject/__pycache__/extra_validations.cpython-311.pyc` | file | `build_artifact_excluded` | 229 | 107 | 33 | 8 | `exclude` |
| `.venv/Lib/site-packages/setuptools/config/_validate_pyproject/__pycache__/fastjsonschema_exceptions.cpython-311.pyc` | file | `build_artifact_excluded` | 237 | 115 | 41 | 8 | `exclude` |
| `.venv/Lib/site-packages/setuptools/config/_validate_pyproject/__pycache__/fastjsonschema_validations.cpython-311.pyc` | file | `build_artifact_excluded` | 238 | 116 | 42 | 8 | `exclude` |
| `.venv/Lib/site-packages/shapely/tests/legacy/__pycache__/test_create_inconsistent_dimensionality.cpython-311.pyc` | file | `build_artifact_excluded` | 234 | 112 | 55 | 8 | `exclude` |
| `.venv/Lib/site-packages/sklearn/datasets/tests/data/openml/id_1119/api-v1-jdl-dn-adult-census-l-2-dv-1.json.gz` | file | `build_artifact_excluded` | 232 | 110 | 43 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/datasets/tests/data/openml/id_1119/api-v1-jdl-dn-adult-census-l-2-s-act-.json.gz` | file | `build_artifact_excluded` | 234 | 112 | 45 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/datasets/tests/data/openml/id_292/api-v1-jdl-dn-australian-l-2-dv-1-s-dact.json.gz` | file | `build_artifact_excluded` | 236 | 114 | 48 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/datasets/tests/data/openml/id_292/api-v1-jdl-dn-australian-l-2-dv-1.json.gz` | file | `build_artifact_excluded` | 229 | 107 | 41 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/datasets/tests/data/openml/id_292/api-v1-jdl-dn-australian-l-2-s-act-.json.gz` | file | `build_artifact_excluded` | 231 | 109 | 43 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/datasets/tests/data/openml/id_40589/api-v1-jdl-dn-emotions-l-2-dv-3.json.gz` | file | `build_artifact_excluded` | 229 | 107 | 39 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/datasets/tests/data/openml/id_40589/api-v1-jdl-dn-emotions-l-2-s-act-.json.gz` | file | `build_artifact_excluded` | 231 | 109 | 41 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/datasets/tests/data/openml/id_40675/api-v1-jdl-dn-glass2-l-2-dv-1-s-dact.json.gz` | file | `build_artifact_excluded` | 234 | 112 | 44 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/datasets/tests/data/openml/id_40675/api-v1-jdl-dn-glass2-l-2-dv-1.json.gz` | file | `build_artifact_excluded` | 227 | 105 | 37 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/datasets/tests/data/openml/id_40675/api-v1-jdl-dn-glass2-l-2-s-act-.json.gz` | file | `build_artifact_excluded` | 229 | 107 | 39 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/datasets/tests/data/openml/id_40966/api-v1-jdl-dn-miceprotein-l-2-dv-4.json.gz` | file | `build_artifact_excluded` | 232 | 110 | 42 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/datasets/tests/data/openml/id_40966/api-v1-jdl-dn-miceprotein-l-2-s-act-.json.gz` | file | `build_artifact_excluded` | 234 | 112 | 44 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/ensemble/_hist_gradient_boosting/__pycache__/gradient_boosting.cpython-311.pyc` | file | `build_artifact_excluded` | 232 | 110 | 33 | 8 | `exclude` |
| `.venv/Lib/site-packages/sklearn/ensemble/_hist_gradient_boosting/tests/__pycache__/__init__.cpython-311.pyc` | file | `build_artifact_excluded` | 229 | 107 | 24 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/ensemble/_hist_gradient_boosting/tests/__pycache__/test_binning.cpython-311.pyc` | file | `build_artifact_excluded` | 233 | 111 | 28 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/ensemble/_hist_gradient_boosting/tests/__pycache__/test_compare_lightgbm.cpython-311.pyc` | file | `build_artifact_excluded` | 242 | 120 | 37 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/ensemble/_hist_gradient_boosting/tests/__pycache__/test_gradient_boosting.cpython-311.pyc` | file | `build_artifact_excluded` | 243 | 121 | 38 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/ensemble/_hist_gradient_boosting/tests/__pycache__/test_grower.cpython-311.pyc` | file | `build_artifact_excluded` | 232 | 110 | 27 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/ensemble/_hist_gradient_boosting/tests/__pycache__/test_histogram.cpython-311.pyc` | file | `build_artifact_excluded` | 235 | 113 | 30 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/ensemble/_hist_gradient_boosting/tests/__pycache__/test_monotonic_constraints.cpython-311.pyc` | file | `build_artifact_excluded` | 247 | 125 | 42 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/ensemble/_hist_gradient_boosting/tests/__pycache__/test_predictor.cpython-311.pyc` | file | `build_artifact_excluded` | 235 | 113 | 30 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/ensemble/_hist_gradient_boosting/tests/__pycache__/test_splitting.cpython-311.pyc` | file | `build_artifact_excluded` | 235 | 113 | 30 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/ensemble/_hist_gradient_boosting/tests/__pycache__/test_warm_start.cpython-311.pyc` | file | `build_artifact_excluded` | 236 | 114 | 31 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/experimental/tests/__pycache__/test_enable_hist_gradient_boosting.cpython-311.pyc` | file | `build_artifact_excluded` | 235 | 113 | 50 | 8 | `exclude` |
| `.venv/Lib/site-packages/sklearn/experimental/tests/__pycache__/test_enable_iterative_imputer.cpython-311.pyc` | file | `build_artifact_excluded` | 230 | 108 | 45 | 8 | `exclude` |
| `.venv/Lib/site-packages/sklearn/experimental/tests/__pycache__/test_enable_successive_halving.cpython-311.pyc` | file | `build_artifact_excluded` | 231 | 109 | 46 | 8 | `exclude` |
| `.venv/Lib/site-packages/sklearn/externals/array_api_compat/dask/array/__pycache__/__init__.cpython-311.pyc` | file | `build_artifact_excluded` | 228 | 106 | 24 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/externals/array_api_compat/dask/array/__pycache__/_aliases.cpython-311.pyc` | file | `build_artifact_excluded` | 228 | 106 | 24 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/externals/array_api_extra/_lib/_utils/__pycache__/__init__.cpython-311.pyc` | file | `build_artifact_excluded` | 228 | 106 | 24 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/externals/array_api_extra/_lib/_utils/__pycache__/_compat.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 23 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/externals/array_api_extra/_lib/_utils/__pycache__/_helpers.cpython-311.pyc` | file | `build_artifact_excluded` | 228 | 106 | 24 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/externals/array_api_extra/_lib/_utils/__pycache__/_typing.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 23 | 10 | `exclude` |
| `.venv/Lib/site-packages/sklearn/feature_extraction/tests/__pycache__/test_dict_vectorizer.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 36 | 8 | `exclude` |
| `.venv/Lib/site-packages/sklearn/feature_selection/tests/__pycache__/test_variance_threshold.cpython-311.pyc` | file | `build_artifact_excluded` | 229 | 107 | 39 | 8 | `exclude` |
| `.venv/Lib/site-packages/sklearn/inspection/_plot/tests/__pycache__/test_boundary_decision_display.cpython-311.pyc` | file | `build_artifact_excluded` | 235 | 113 | 46 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/inspection/_plot/tests/__pycache__/test_plot_partial_dependence.cpython-311.pyc` | file | `build_artifact_excluded` | 233 | 111 | 44 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/linear_model/tests/__pycache__/test_sparse_coordinate_descent.cpython-311.pyc` | file | `build_artifact_excluded` | 231 | 109 | 46 | 8 | `exclude` |
| `.venv/Lib/site-packages/sklearn/metrics/_pairwise_distances_reduction/__pycache__/__init__.cpython-311.pyc` | file | `build_artifact_excluded` | 228 | 106 | 29 | 8 | `exclude` |
| `.venv/Lib/site-packages/sklearn/metrics/_pairwise_distances_reduction/__pycache__/_dispatcher.cpython-311.pyc` | file | `build_artifact_excluded` | 231 | 109 | 29 | 8 | `exclude` |
| `.venv/Lib/site-packages/sklearn/metrics/_pairwise_distances_reduction/_argkmin_classmode.cp311-win_amd64.lib` | file | `build_artifact_excluded` | 230 | 108 | 38 | 7 | `exclude` |
| `.venv/Lib/site-packages/sklearn/metrics/_pairwise_distances_reduction/_argkmin_classmode.cp311-win_amd64.pyd` | file | `build_artifact_excluded` | 230 | 108 | 38 | 7 | `exclude` |
| `.venv/Lib/site-packages/sklearn/metrics/_pairwise_distances_reduction/_middle_term_computer.cp311-win_amd64.lib` | file | `build_artifact_excluded` | 233 | 111 | 41 | 7 | `exclude` |
| `.venv/Lib/site-packages/sklearn/metrics/_pairwise_distances_reduction/_middle_term_computer.cp311-win_amd64.pyd` | file | `build_artifact_excluded` | 233 | 111 | 41 | 7 | `exclude` |
| `.venv/Lib/site-packages/sklearn/metrics/_pairwise_distances_reduction/_radius_neighbors.cp311-win_amd64.lib` | file | `build_artifact_excluded` | 229 | 107 | 37 | 7 | `exclude` |
| `.venv/Lib/site-packages/sklearn/metrics/_pairwise_distances_reduction/_radius_neighbors.cp311-win_amd64.pyd` | file | `build_artifact_excluded` | 229 | 107 | 37 | 7 | `exclude` |
| `.venv/Lib/site-packages/sklearn/metrics/_pairwise_distances_reduction/_radius_neighbors_classmode.cp311-win_amd64.lib` | file | `build_artifact_excluded` | 239 | 117 | 47 | 7 | `exclude` |
| `.venv/Lib/site-packages/sklearn/metrics/_pairwise_distances_reduction/_radius_neighbors_classmode.cp311-win_amd64.pyd` | file | `build_artifact_excluded` | 239 | 117 | 47 | 7 | `exclude` |
| `.venv/Lib/site-packages/sklearn/metrics/_plot/tests/__pycache__/test_common_curve_display.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 41 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/metrics/_plot/tests/__pycache__/test_confusion_matrix_display.cpython-311.pyc` | file | `build_artifact_excluded` | 231 | 109 | 45 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/metrics/_plot/tests/__pycache__/test_precision_recall_display.cpython-311.pyc` | file | `build_artifact_excluded` | 231 | 109 | 45 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/metrics/_plot/tests/__pycache__/test_predict_error_display.cpython-311.pyc` | file | `build_artifact_excluded` | 228 | 106 | 42 | 9 | `exclude` |
| `.venv/Lib/site-packages/sklearn/metrics/tests/__pycache__/test_pairwise_distances_reduction.cpython-311.pyc` | file | `build_artifact_excluded` | 229 | 107 | 49 | 8 | `exclude` |
| `.venv/Lib/site-packages/sklearn/model_selection/tests/__pycache__/test_classification_threshold.cpython-311.pyc` | file | `build_artifact_excluded` | 233 | 111 | 45 | 8 | `exclude` |
| `.venv/Lib/site-packages/sklearn/model_selection/tests/__pycache__/test_successive_halving.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 39 | 8 | `exclude` |
| `.venv/Lib/site-packages/sklearn/neural_network/tests/__pycache__/test_stochastic_optimizers.cpython-311.pyc` | file | `build_artifact_excluded` | 229 | 107 | 42 | 8 | `exclude` |
| `.venv/Lib/site-packages/sklearn/preprocessing/tests/__pycache__/test_function_transformer.cpython-311.pyc` | file | `build_artifact_excluded` | 227 | 105 | 41 | 8 | `exclude` |
| `node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/codex-resources/codex-command-runner.exe` | file | `build_artifact_excluded` | 229 | 107 | 24 | 7 | `exclude` |
| `node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/codex-resources/codex-windows-sandbox-setup.exe` | file | `build_artifact_excluded` | 236 | 114 | 31 | 7 | `exclude` |
| `state/browser-profile/component_crx_cache/261bea60d22ebca3a95ce335c03ec751a0b58b2b7bdbd6ea51dfa54381b07775` | file | `technical_cache_excluded` | 228 | 106 | 64 | 4 | `exclude` |
| `state/browser-profile/component_crx_cache/3c490cd0abb97f15040e4aaa68dc4f1eae73b73591c29ae082ea6c5b364abe94` | file | `technical_cache_excluded` | 228 | 106 | 64 | 4 | `exclude` |
| `state/browser-profile/component_crx_cache/3eb16d6c28b502ac4cfee8f4a148df05f4d93229fa36a71db8b08d06329ff18a` | file | `technical_cache_excluded` | 228 | 106 | 64 | 4 | `exclude` |
| `state/browser-profile/component_crx_cache/4448b37acb13eb51a842a8ebc85ea826729571c7293f2213d855d3a76cb9a4f8` | file | `technical_cache_excluded` | 228 | 106 | 64 | 4 | `exclude` |
| `state/browser-profile/component_crx_cache/7b05c14dba04ed522210b733f004cb0e74d7679a653b19bd029f9bc0e6b19903` | file | `technical_cache_excluded` | 228 | 106 | 64 | 4 | `exclude` |
| `state/browser-profile/component_crx_cache/8d5b9d356a90c016c701e9272b364929cc6c033333fa2e96fdf155cd85108382` | file | `technical_cache_excluded` | 228 | 106 | 64 | 4 | `exclude` |
| `state/browser-profile/component_crx_cache/8f2c0712b6800fa9622a039cb167cc9503d508a271247e445f08a96eded5772f` | file | `technical_cache_excluded` | 228 | 106 | 64 | 4 | `exclude` |
| `state/browser-profile/component_crx_cache/9bec6c2c0185d3305ac8495047a1aa01e725d58f8f18d219742a2988f07cd93a` | file | `technical_cache_excluded` | 228 | 106 | 64 | 4 | `exclude` |
| `state/browser-profile/component_crx_cache/9e27f42e99874979c080c30ca70f373a15a2e8c474cc59fb7adbbd6062248f35` | file | `technical_cache_excluded` | 228 | 106 | 64 | 4 | `exclude` |
| `state/browser-profile/component_crx_cache/abd93867c038d4d17c101ace2226d7e21303d984d7097271392bae6be478495b` | file | `technical_cache_excluded` | 228 | 106 | 64 | 4 | `exclude` |
| `state/browser-profile/component_crx_cache/ae216724654f3e52d3c502328caf83f773e66cc5818c38850165864005a35169` | file | `technical_cache_excluded` | 228 | 106 | 64 | 4 | `exclude` |
| `state/browser-profile/component_crx_cache/c8c2fd0acdb7eecaf4f66d5164204c4e8e5ebbabb6398e0ee6ec6d8af71ea672` | file | `technical_cache_excluded` | 228 | 106 | 64 | 4 | `exclude` |
| `state/browser-profile/component_crx_cache/ce74b9332fb99d2641699568857fae1af09af981c7db763d3cb68cc9bdcc50db` | file | `technical_cache_excluded` | 228 | 106 | 64 | 4 | `exclude` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/bg/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/ca/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/cs/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/da/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/de/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/el/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/en/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/en_GB/messages.json` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/es/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/es_419/messages.json` | file | `runtime_state_metadata_only` | 235 | 113 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/et/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/fi/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/fil/messages.json` | file | `runtime_state_metadata_only` | 232 | 110 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/fr/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/hi/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/hr/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/hu/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/id/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/it/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/ja/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/ko/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/lt/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/lv/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/nb/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/nl/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/pl/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/pt_BR/messages.json` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/pt_PT/messages.json` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/ro/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/ru/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/sk/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/sl/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/sr/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/sv/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/th/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/tr/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/uk/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/vi/messages.json` | file | `runtime_state_metadata_only` | 231 | 109 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/zh_CN/messages.json` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_locales/zh_TW/messages.json` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_metadata/computed_hashes.json` | file | `runtime_state_metadata_only` | 236 | 114 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/_metadata/verified_contents.json` | file | `runtime_state_metadata_only` | 238 | 116 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/html/craw_window.html` | file | `runtime_state_metadata_only` | 227 | 105 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/images/topbar_floating_button.png` | file | `runtime_state_metadata_only` | 239 | 117 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/images/topbar_floating_button_close.png` | file | `runtime_state_metadata_only` | 245 | 123 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/images/topbar_floating_button_hover.png` | file | `runtime_state_metadata_only` | 245 | 123 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Extensions/nmmhkkegccagdldgiimedpiccmgmieda/1.0.0.6_0/images/topbar_floating_button_pressed.png` | file | `runtime_state_metadata_only` | 247 | 125 | 34 | 8 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/0bf6ab7f94a21cdc9c1649f884333ec20f40a544/index.txt` | file | `runtime_state_metadata_only` | 230 | 108 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/3cedfb74d44f2e84198d23075aef16c34a668ceb/index.txt` | file | `runtime_state_metadata_only` | 230 | 108 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Default/Service Worker/CacheStorage/4cc699dd486af2551d01b1a74abd5337c6e052e5/index.txt` | file | `runtime_state_metadata_only` | 230 | 108 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Code Cache/js/6f3a0dc5e6916f1e_0` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 10 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Code Cache/js/index-dir/the-real-index` | file | `runtime_state_metadata_only` | 239 | 117 | 32 | 11 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Code Cache/wasm/index-dir/the-real-index` | file | `runtime_state_metadata_only` | 241 | 119 | 32 | 11 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Local Storage/leveldb/000003.log` | file | `temporary_excluded` | 233 | 111 | 32 | 10 | `exclude` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Local Storage/leveldb/CURRENT` | file | `runtime_state_metadata_only` | 230 | 108 | 32 | 10 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Local Storage/leveldb/LOCK` | file | `runtime_state_metadata_only` | 227 | 105 | 32 | 10 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Local Storage/leveldb/MANIFEST-000001` | file | `runtime_state_metadata_only` | 238 | 116 | 32 | 10 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Network/Device Bound Sessions` | file | `runtime_state_metadata_only` | 230 | 108 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Network/Device Bound Sessions-journal` | file | `runtime_state_metadata_only` | 238 | 116 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Network/Network Persistent State` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Network/NetworkDataMigrated` | file | `runtime_state_metadata_only` | 228 | 106 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Network/SCT Auditing Pending Reports` | file | `runtime_state_metadata_only` | 237 | 115 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Network/Trust Tokens-journal` | file | `runtime_state_metadata_only` | 229 | 107 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Session Storage/000003.log` | file | `temporary_excluded` | 227 | 105 | 32 | 9 | `exclude` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Session Storage/MANIFEST-000001` | file | `runtime_state_metadata_only` | 232 | 110 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Shared Dictionary/cache/index` | file | `technical_cache_excluded` | 230 | 108 | 32 | 10 | `exclude` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Shared Dictionary/cache/index-dir` | directory | `technical_cache_excluded` | 234 | 112 | 32 | 10 | `exclude` |
| `state/browser-profile/Default/Storage/ext/ihmafllikibpmigkcoadcmckbfhibefp/def/Shared Dictionary/db-journal` | file | `runtime_state_metadata_only` | 229 | 107 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Code Cache/js/5dea14b9816ec6d9_0` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 10 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Code Cache/js/index-dir/the-real-index` | file | `runtime_state_metadata_only` | 239 | 117 | 32 | 11 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Code Cache/wasm/index-dir/the-real-index` | file | `runtime_state_metadata_only` | 241 | 119 | 32 | 11 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Local Storage/leveldb/000003.log` | file | `temporary_excluded` | 233 | 111 | 32 | 10 | `exclude` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Local Storage/leveldb/CURRENT` | file | `runtime_state_metadata_only` | 230 | 108 | 32 | 10 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Local Storage/leveldb/LOCK` | file | `runtime_state_metadata_only` | 227 | 105 | 32 | 10 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Local Storage/leveldb/MANIFEST-000001` | file | `runtime_state_metadata_only` | 238 | 116 | 32 | 10 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Network/Device Bound Sessions` | file | `runtime_state_metadata_only` | 230 | 108 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Network/Device Bound Sessions-journal` | file | `runtime_state_metadata_only` | 238 | 116 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Network/Network Persistent State` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Network/NetworkDataMigrated` | file | `runtime_state_metadata_only` | 228 | 106 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Network/Trust Tokens-journal` | file | `runtime_state_metadata_only` | 229 | 107 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Session Storage/000003.log` | file | `temporary_excluded` | 227 | 105 | 32 | 9 | `exclude` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Session Storage/MANIFEST-000001` | file | `runtime_state_metadata_only` | 232 | 110 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Shared Dictionary/cache/index` | file | `technical_cache_excluded` | 230 | 108 | 32 | 10 | `exclude` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Shared Dictionary/cache/index-dir` | directory | `technical_cache_excluded` | 234 | 112 | 32 | 10 | `exclude` |
| `state/browser-profile/Default/Storage/ext/nmmhkkegccagdldgiimedpiccmgmieda/def/Shared Dictionary/db-journal` | file | `runtime_state_metadata_only` | 229 | 107 | 32 | 9 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/aghbiahbpaijignceidepookljebhfak/Icons Maskable` | directory | `runtime_state_metadata_only` | 235 | 113 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/aghbiahbpaijignceidepookljebhfak/Icons Monochrome` | directory | `runtime_state_metadata_only` | 237 | 115 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/aghbiahbpaijignceidepookljebhfak/Icons/128.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/aghbiahbpaijignceidepookljebhfak/Icons/192.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/aghbiahbpaijignceidepookljebhfak/Icons/256.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/aghbiahbpaijignceidepookljebhfak/Icons/32.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/aghbiahbpaijignceidepookljebhfak/Icons/48.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/aghbiahbpaijignceidepookljebhfak/Icons/64.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/aghbiahbpaijignceidepookljebhfak/Icons/96.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/aghbiahbpaijignceidepookljebhfak/Trusted Icons` | directory | `runtime_state_metadata_only` | 234 | 112 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/aghbiahbpaijignceidepookljebhfak/Trusted Icons/Icons` | directory | `runtime_state_metadata_only` | 240 | 118 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/agimnkijcaahngcdmfeangaknmldooml/Icons Maskable` | directory | `runtime_state_metadata_only` | 235 | 113 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/agimnkijcaahngcdmfeangaknmldooml/Icons Monochrome` | directory | `runtime_state_metadata_only` | 237 | 115 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/agimnkijcaahngcdmfeangaknmldooml/Icons/128.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/agimnkijcaahngcdmfeangaknmldooml/Icons/192.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/agimnkijcaahngcdmfeangaknmldooml/Icons/256.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/agimnkijcaahngcdmfeangaknmldooml/Icons/32.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/agimnkijcaahngcdmfeangaknmldooml/Icons/48.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/agimnkijcaahngcdmfeangaknmldooml/Icons/64.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/agimnkijcaahngcdmfeangaknmldooml/Icons/96.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/agimnkijcaahngcdmfeangaknmldooml/Trusted Icons` | directory | `runtime_state_metadata_only` | 234 | 112 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/agimnkijcaahngcdmfeangaknmldooml/Trusted Icons/Icons` | directory | `runtime_state_metadata_only` | 240 | 118 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fhihpiojkbmbpdjeoajapmgkhlnakfjf/Icons Maskable` | directory | `runtime_state_metadata_only` | 235 | 113 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fhihpiojkbmbpdjeoajapmgkhlnakfjf/Icons Monochrome` | directory | `runtime_state_metadata_only` | 237 | 115 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fhihpiojkbmbpdjeoajapmgkhlnakfjf/Icons/128.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fhihpiojkbmbpdjeoajapmgkhlnakfjf/Icons/192.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fhihpiojkbmbpdjeoajapmgkhlnakfjf/Icons/256.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fhihpiojkbmbpdjeoajapmgkhlnakfjf/Icons/32.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fhihpiojkbmbpdjeoajapmgkhlnakfjf/Icons/48.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fhihpiojkbmbpdjeoajapmgkhlnakfjf/Icons/64.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fhihpiojkbmbpdjeoajapmgkhlnakfjf/Icons/96.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fhihpiojkbmbpdjeoajapmgkhlnakfjf/Trusted Icons` | directory | `runtime_state_metadata_only` | 234 | 112 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fhihpiojkbmbpdjeoajapmgkhlnakfjf/Trusted Icons/Icons` | directory | `runtime_state_metadata_only` | 240 | 118 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fmgjjmmmlfnkbppncabfkddbjimcfncm/Icons Maskable` | directory | `runtime_state_metadata_only` | 235 | 113 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fmgjjmmmlfnkbppncabfkddbjimcfncm/Icons Monochrome` | directory | `runtime_state_metadata_only` | 237 | 115 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fmgjjmmmlfnkbppncabfkddbjimcfncm/Icons/128.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fmgjjmmmlfnkbppncabfkddbjimcfncm/Icons/192.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fmgjjmmmlfnkbppncabfkddbjimcfncm/Icons/256.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fmgjjmmmlfnkbppncabfkddbjimcfncm/Icons/32.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fmgjjmmmlfnkbppncabfkddbjimcfncm/Icons/48.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fmgjjmmmlfnkbppncabfkddbjimcfncm/Icons/64.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fmgjjmmmlfnkbppncabfkddbjimcfncm/Icons/96.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fmgjjmmmlfnkbppncabfkddbjimcfncm/Trusted Icons` | directory | `runtime_state_metadata_only` | 234 | 112 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/fmgjjmmmlfnkbppncabfkddbjimcfncm/Trusted Icons/Icons` | directory | `runtime_state_metadata_only` | 240 | 118 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/kefjledonklijopmnomlcbpllchaibag/Icons Maskable` | directory | `runtime_state_metadata_only` | 235 | 113 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/kefjledonklijopmnomlcbpllchaibag/Icons Monochrome` | directory | `runtime_state_metadata_only` | 237 | 115 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/kefjledonklijopmnomlcbpllchaibag/Icons/128.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/kefjledonklijopmnomlcbpllchaibag/Icons/192.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/kefjledonklijopmnomlcbpllchaibag/Icons/256.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/kefjledonklijopmnomlcbpllchaibag/Icons/32.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/kefjledonklijopmnomlcbpllchaibag/Icons/48.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/kefjledonklijopmnomlcbpllchaibag/Icons/64.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/kefjledonklijopmnomlcbpllchaibag/Icons/96.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/kefjledonklijopmnomlcbpllchaibag/Trusted Icons` | directory | `runtime_state_metadata_only` | 234 | 112 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/kefjledonklijopmnomlcbpllchaibag/Trusted Icons/Icons` | directory | `runtime_state_metadata_only` | 240 | 118 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/mpnpojknpmmopombnjdcgaaiekajbnjb/Icons Maskable` | directory | `runtime_state_metadata_only` | 235 | 113 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/mpnpojknpmmopombnjdcgaaiekajbnjb/Icons Monochrome` | directory | `runtime_state_metadata_only` | 237 | 115 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/mpnpojknpmmopombnjdcgaaiekajbnjb/Icons/128.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/mpnpojknpmmopombnjdcgaaiekajbnjb/Icons/192.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/mpnpojknpmmopombnjdcgaaiekajbnjb/Icons/256.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/mpnpojknpmmopombnjdcgaaiekajbnjb/Icons/32.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/mpnpojknpmmopombnjdcgaaiekajbnjb/Icons/48.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/mpnpojknpmmopombnjdcgaaiekajbnjb/Icons/64.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/mpnpojknpmmopombnjdcgaaiekajbnjb/Icons/96.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/mpnpojknpmmopombnjdcgaaiekajbnjb/Trusted Icons` | directory | `runtime_state_metadata_only` | 234 | 112 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/mpnpojknpmmopombnjdcgaaiekajbnjb/Trusted Icons/Icons` | directory | `runtime_state_metadata_only` | 240 | 118 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/pommaclcbfghclhalboakcipcmmndhcj/Icons Maskable` | directory | `runtime_state_metadata_only` | 235 | 113 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/pommaclcbfghclhalboakcipcmmndhcj/Icons Monochrome` | directory | `runtime_state_metadata_only` | 237 | 115 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/pommaclcbfghclhalboakcipcmmndhcj/Icons/128.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/pommaclcbfghclhalboakcipcmmndhcj/Icons/192.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/pommaclcbfghclhalboakcipcmmndhcj/Icons/256.png` | file | `runtime_state_metadata_only` | 234 | 112 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/pommaclcbfghclhalboakcipcmmndhcj/Icons/32.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/pommaclcbfghclhalboakcipcmmndhcj/Icons/48.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/pommaclcbfghclhalboakcipcmmndhcj/Icons/64.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/pommaclcbfghclhalboakcipcmmndhcj/Icons/96.png` | file | `runtime_state_metadata_only` | 233 | 111 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/pommaclcbfghclhalboakcipcmmndhcj/Trusted Icons` | directory | `runtime_state_metadata_only` | 234 | 112 | 32 | 7 | `metadata_only` |
| `state/browser-profile/Default/Web Applications/Manifest Resources/pommaclcbfghclhalboakcipcmmndhcj/Trusted Icons/Icons` | directory | `runtime_state_metadata_only` | 240 | 118 | 32 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/2.0.0-DeepEEEnUs/metadata.json` | file | `runtime_state_metadata_only` | 227 | 105 | 22 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/2.0.0-DeepEEEnUsProductByRegexOnly` | directory | `runtime_state_metadata_only` | 231 | 109 | 34 | 6 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/2.0.0-DeepEEEnUsProductByRegexOnly/asset` | file | `runtime_state_metadata_only` | 237 | 115 | 34 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/2.0.0-DeepEEEnUsProductByRegexOnly/metadata.json` | file | `runtime_state_metadata_only` | 245 | 123 | 34 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/3.0.0-DeepEEEnUs/metadata.json` | file | `runtime_state_metadata_only` | 227 | 105 | 22 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/3.0.0-DeepEEEnUsProductByRegexOnly` | directory | `runtime_state_metadata_only` | 231 | 109 | 34 | 6 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/3.0.0-DeepEEEnUsProductByRegexOnly/asset` | file | `runtime_state_metadata_only` | 237 | 115 | 34 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/3.0.0-DeepEEEnUsProductByRegexOnly/metadata.json` | file | `runtime_state_metadata_only` | 245 | 123 | 34 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/3.0.0-DeepEEEnUsRegexOnly/asset` | file | `runtime_state_metadata_only` | 228 | 106 | 25 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/3.0.0-DeepEEEnUsRegexOnly/metadata.json` | file | `runtime_state_metadata_only` | 236 | 114 | 25 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/3.0.0-DeepEEUrlCategoryRegex/asset` | file | `runtime_state_metadata_only` | 231 | 109 | 28 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/3.0.0-DeepEEUrlCategoryRegex/metadata.json` | file | `runtime_state_metadata_only` | 239 | 117 | 28 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/3.0.0-DeepEEUrlCategoryRegexCustom` | directory | `runtime_state_metadata_only` | 231 | 109 | 34 | 6 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/3.0.0-DeepEEUrlCategoryRegexCustom/asset` | file | `runtime_state_metadata_only` | 237 | 115 | 34 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/3.0.0-DeepEEUrlCategoryRegexCustom/metadata.json` | file | `runtime_state_metadata_only` | 245 | 123 | 34 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/3.0.0-HeuristicClassifierOptimization` | directory | `runtime_state_metadata_only` | 234 | 112 | 37 | 6 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/domains_config_gz/3.0.0-HeuristicClassifierOptimization/asset` | file | `runtime_state_metadata_only` | 240 | 118 | 37 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/2.0.0-DeepEEEnUs/asset` | file | `runtime_state_metadata_only` | 231 | 109 | 22 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/2.0.0-DeepEEEnUs/metadata.json` | file | `runtime_state_metadata_only` | 239 | 117 | 22 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/2.0.0-DeepEEEnUsProductByRegexOnly` | directory | `runtime_state_metadata_only` | 243 | 121 | 34 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/2.0.0/metadata.json` | file | `runtime_state_metadata_only` | 228 | 106 | 22 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-DeepEEEnUs/asset` | file | `runtime_state_metadata_only` | 231 | 109 | 22 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-DeepEEEnUs/metadata.json` | file | `runtime_state_metadata_only` | 239 | 117 | 22 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-DeepEEEnUsProductByRegexOnly` | directory | `runtime_state_metadata_only` | 243 | 121 | 34 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-DeepEEEnUsRegexOnly` | directory | `runtime_state_metadata_only` | 234 | 112 | 25 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-DeepEEEnUsRegexOnly/asset` | file | `runtime_state_metadata_only` | 240 | 118 | 25 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-DeepEEUrlCategoryRegex` | directory | `runtime_state_metadata_only` | 237 | 115 | 28 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-DeepEEUrlCategoryRegex/asset` | file | `runtime_state_metadata_only` | 243 | 121 | 28 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-DeepEEUrlCategoryRegexCustom` | directory | `runtime_state_metadata_only` | 243 | 121 | 34 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0-HeuristicClassifierOptimization` | directory | `runtime_state_metadata_only` | 246 | 124 | 37 | 7 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/domains_config_gz/3.0.0/metadata.json` | file | `runtime_state_metadata_only` | 228 | 106 | 22 | 8 | `metadata_only` |
| `state/browser-profile/Edge Entity Extraction/2026.6.30.7/pre-release/onnx.product.desktop.de/3.2.3/metadata.json` | file | `runtime_state_metadata_only` | 234 | 112 | 23 | 8 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_compose_maximal_dark.png/1.0.2/metadata.json` | file | `runtime_state_metadata_only` | 227 | 105 | 38 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_compose_maximal_light.png/1.0.2/metadata.json` | file | `runtime_state_metadata_only` | 228 | 106 | 39 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_controller_maximal_dark.png/1.0.11/metadata.json` | file | `runtime_state_metadata_only` | 231 | 109 | 41 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_controller_maximal_light.png/1.0.11/metadata.json` | file | `runtime_state_metadata_only` | 232 | 110 | 42 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_discover_maximal_color_dark.png/0.0.8/metadata.json` | file | `runtime_state_metadata_only` | 234 | 112 | 45 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_discover_maximal_color_light.png/0.0.8/asset` | file | `runtime_state_metadata_only` | 227 | 105 | 46 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_discover_maximal_color_light.png/0.0.8/metadata.json` | file | `runtime_state_metadata_only` | 235 | 113 | 46 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_discover_maximal_monoline_light.png/0.0.8/asset` | file | `runtime_state_metadata_only` | 230 | 108 | 49 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_discover_maximal_monoline_light.png/0.0.8/metadata.json` | file | `runtime_state_metadata_only` | 238 | 116 | 49 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_edrop_maximal_light.png/1.1.18/metadata.json` | file | `runtime_state_metadata_only` | 227 | 105 | 37 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_facebook_messenger_hc.png/0.0.8/metadata.json` | file | `runtime_state_metadata_only` | 228 | 106 | 39 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_games_hc_controller.png/1.7.18/metadata.json` | file | `runtime_state_metadata_only` | 227 | 105 | 37 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_games_maximal_dark_card.png/1.7.18/metadata.json` | file | `runtime_state_metadata_only` | 231 | 109 | 41 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_games_maximal_dark_controller.png/1.7.18/asset` | file | `runtime_state_metadata_only` | 229 | 107 | 47 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_games_maximal_dark_controller.png/1.7.18/metadata.json` | file | `runtime_state_metadata_only` | 237 | 115 | 47 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_games_maximal_dark_joystick.png/1.7.18/asset` | file | `runtime_state_metadata_only` | 227 | 105 | 45 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_games_maximal_dark_joystick.png/1.7.18/metadata.json` | file | `runtime_state_metadata_only` | 235 | 113 | 45 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_games_maximal_dark_puzzle.png/1.7.18/metadata.json` | file | `runtime_state_metadata_only` | 233 | 111 | 43 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_games_maximal_light.png/1.7.18/metadata.json` | file | `runtime_state_metadata_only` | 227 | 105 | 37 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_games_maximal_light_card.png/1.7.18/metadata.json` | file | `runtime_state_metadata_only` | 232 | 110 | 42 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_games_maximal_light_controller.png/1.7.18/asset` | file | `runtime_state_metadata_only` | 230 | 108 | 48 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_games_maximal_light_controller.png/1.7.18/metadata.json` | file | `runtime_state_metadata_only` | 238 | 116 | 48 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_games_maximal_light_joystick.png/1.7.18/asset` | file | `runtime_state_metadata_only` | 228 | 106 | 46 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_games_maximal_light_joystick.png/1.7.18/metadata.json` | file | `runtime_state_metadata_only` | 236 | 114 | 46 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_games_maximal_light_puzzle.png/1.7.18/metadata.json` | file | `runtime_state_metadata_only` | 234 | 112 | 44 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_ImageCreator_DarkMode.png/1.0.25/metadata.json` | file | `runtime_state_metadata_only` | 229 | 107 | 39 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_ImageCreator_HighContrast.png/1.0.25/metadata.json` | file | `runtime_state_metadata_only` | 233 | 111 | 43 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_ImageCreator_LightMode.png/1.0.25/metadata.json` | file | `runtime_state_metadata_only` | 230 | 108 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_maximal_discover_dark.png/0.0.8/metadata.json` | file | `runtime_state_metadata_only` | 228 | 106 | 39 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_maximal_discover_light.png/0.0.8/metadata.json` | file | `runtime_state_metadata_only` | 229 | 107 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_maximal_follow_light.png/1.1.2/metadata.json` | file | `runtime_state_metadata_only` | 227 | 105 | 38 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_maximal_games_light.png/0.0.13/metadata.json` | file | `runtime_state_metadata_only` | 227 | 105 | 37 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_maximal_search_light.png/0.0.7/metadata.json` | file | `runtime_state_metadata_only` | 227 | 105 | 38 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_maximal_shopping_dark.png/0.0.7/metadata.json` | file | `runtime_state_metadata_only` | 228 | 106 | 39 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_maximal_shopping_light.png/0.0.7/metadata.json` | file | `runtime_state_metadata_only` | 229 | 107 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_maximal_toolbox_dark.png/0.0.7/metadata.json` | file | `runtime_state_metadata_only` | 227 | 105 | 38 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_maximal_toolbox_light.png/0.0.7/metadata.json` | file | `runtime_state_metadata_only` | 228 | 106 | 39 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_performance_maximal_dark.png/1.1.3/metadata.json` | file | `runtime_state_metadata_only` | 231 | 109 | 42 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_performance_maximal_light.png/1.1.3/metadata.json` | file | `runtime_state_metadata_only` | 232 | 110 | 43 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_rewards_maximal_dark.png/1.2.1/metadata.json` | file | `runtime_state_metadata_only` | 227 | 105 | 38 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_rewards_maximal_light.png/1.2.1/metadata.json` | file | `runtime_state_metadata_only` | 228 | 106 | 39 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_search_maximal_dark.png/1.3.20/metadata.json` | file | `runtime_state_metadata_only` | 227 | 105 | 37 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_search_maximal_light.png/1.3.20/metadata.json` | file | `runtime_state_metadata_only` | 228 | 106 | 38 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_shopping_maximal_dark.png/1.5.7/metadata.json` | file | `runtime_state_metadata_only` | 228 | 106 | 39 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_shopping_maximal_light.png/1.5.7/metadata.json` | file | `runtime_state_metadata_only` | 229 | 107 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_StreamCameraIcon_Dark.png/0.0.8/metadata.json` | file | `runtime_state_metadata_only` | 228 | 106 | 39 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_StreamCameraIcon_Light.png/0.0.8/metadata.json` | file | `runtime_state_metadata_only` | 229 | 107 | 40 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_theater_maximal_dark.png/1.0.9/metadata.json` | file | `runtime_state_metadata_only` | 227 | 105 | 38 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_theater_maximal_light.png/1.0.9/metadata.json` | file | `runtime_state_metadata_only` | 228 | 106 | 39 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_toolbox_maximal_dark.png/1.5.18/metadata.json` | file | `runtime_state_metadata_only` | 228 | 106 | 38 | 7 | `metadata_only` |
| `state/browser-profile/Edge Sidebar/2026.2.24.1/edge_hub_apps_toolbox_maximal_light.png/1.5.18/metadata.json` | file | `runtime_state_metadata_only` | 229 | 107 | 39 | 7 | `metadata_only` |
| `state/browser-profile/Edge Wallet/128.18367.18366.1/json/wallet/wallet-checkout-eligible-sites-pre-stable.json` | file | `runtime_state_metadata_only` | 232 | 110 | 46 | 7 | `metadata_only` |
| `state/browser-profile/GPUPersistentCache/DawnGraphiteCache/WRJTYMYAB73RC6HTXXLKRS2FEZVUG6PP/cache.journal` | file | `runtime_state_metadata_only` | 227 | 105 | 32 | 6 | `metadata_only` |
| `state/browser-profile/optimization_guide_model_store/15/EEE9864B3DB2E922/B5BD8CA3D69E3C74/override_list.pb.gz` | file | `runtime_state_metadata_only` | 231 | 109 | 30 | 7 | `metadata_only` |
| `state/browser-profile/optimization_guide_model_store/25/EEE9864B3DB2E922/A171715C816C7643/visual_model_desktop.tflite` | file | `runtime_state_metadata_only` | 239 | 117 | 30 | 7 | `metadata_only` |
| `state/browser-profile/optimization_guide_model_store/43/EEE9864B3DB2E922/E2041CA86B6A4DD0/sentencepiece.model` | file | `runtime_state_metadata_only` | 231 | 109 | 30 | 7 | `metadata_only` |
| `state/models/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120/config.json` | file | `model_artifact_metadata_only` | 235 | 113 | 40 | 6 | `metadata_only` |
| `state/models/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120/model.bin` | file | `model_artifact_metadata_only` | 233 | 111 | 40 | 6 | `metadata_only` |
| `state/models/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120/tokenizer.json` | file | `model_artifact_metadata_only` | 238 | 116 | 40 | 6 | `metadata_only` |
| `state/models/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120/vocabulary.txt` | file | `model_artifact_metadata_only` | 238 | 116 | 40 | 6 | `metadata_only` |
| `state/models/piper/.cache/huggingface/download/de/de_DE/thorsten/high/de_DE-thorsten-high.onnx.json.metadata` | file | `technical_cache_excluded` | 230 | 108 | 38 | 11 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd` | directory | `technical_cache_excluded` | 228 | 106 | 40 | 6 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de` | directory | `technical_cache_excluded` | 231 | 109 | 40 | 7 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE` | directory | `technical_cache_excluded` | 237 | 115 | 40 | 8 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE/eva_k` | directory | `technical_cache_excluded` | 243 | 121 | 40 | 9 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE/kerstin` | directory | `technical_cache_excluded` | 245 | 123 | 40 | 9 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE/mls` | directory | `technical_cache_excluded` | 241 | 119 | 40 | 9 | `exclude` |
| `state/models/review-cache/models--rhasspy--piper-voices/snapshots/0d907f158acc877ddeebcbf827659ee13bea8bcd/de/de_DE/thorsten` | directory | `technical_cache_excluded` | 246 | 124 | 40 | 9 | `exclude` |

### Pfade mit ungewöhnlich langen Segmenten

| Relativer Pfad | Typ | Kategorie | Zielpfad | Relativ | Segment | Tiefe | Entscheidung |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `state/browser-profile/SmartScreen/RemoteData/edgeSettings_2.0-a82cb2897a8bf9445d68dcc2be05af89ad4b2fda1fddb2952693be7cd5353ad3` | file | `runtime_state_metadata_only` | 248 | 126 | 81 | 5 | `metadata_only` |

### Unbekannte Pfade

Keine. `unknown_review_required = 0`.

## Planender Vergleich der Zielstrategien

| Variante | Zuverlässigkeit | Restore | Windows | Risiko | Portabilität | Codeänderung | Urteil |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Langes externes Verzeichnisziel | Mittel | Direkter Tree-Restore | Langpfade bleiben relevant | Teilkopie muss atomar verhindert werden | Hoch | Policy-Filter und Preflight | Nicht bevorzugt |
| Kurzes externes Staging-Ziel | Hoch für Content | Direkter Tree-Restore | Beste Pfadreserve | Zusätzlicher sicherer Staging-Root | Mittel | Root-Allowlist und Cleanup | Geeignet für Restore-Probe |
| Archivcontainer plus SHA-256-Manifest | Hoch | Extraktion plus Manifestprüfung | Keine langen physischen Backup-Unterbäume | Archiv muss atomar und traversal-sicher sein | Hoch | Sicherer Archivwriter/-reader | **Empfohlen** |
| Windows-Long-Path-Präfix | Technisch hoch | Windows-spezifisch | Abhängig von APIs/Policy | Kann fachlich falsche Cachekopien kaschieren | Niedrig | Durchgehende Extended-Path-Unterstützung | Nur interne Metadatenanalyse |

Empfehlung ist ein atomar erzeugter Archivcontainer mit SHA-256-Manifest für den migrationsrelevanten Content. Eine Restore-Probe darf ein kurzes, isoliertes Staging-Ziel verwenden. Long-Path-Präfixe sollen keine Cache-, Modell- oder Runtime-Daten in den Content-Backup ziehen.

## Policy-Simulation

- Ergebnis: `PASS`
- Source/Destination disjunkt: `true`
- unbekannte Pfade: 0
- unbekannte Langpfade: 0
- migrationsrelevante Langpfade: 0
- technische/sensitive Pfade im Content-Backup: 0
- nicht verfolgte Reparse Points: 0
- Verletzungen: `none`

Der Planungsmodus erzeugte kein Backupziel. Die vollständige externe Planungsdatei enthält für jeden Pfad genau eine Kategorie, Größe, Typ, Zielpfadlänge und Entscheidung; sie enthält keine Dateiinhalte oder Hashes.

## Eindeutige Vault-Hashbezeichnungen

- `vault_source_manifest_sha256`: `4f0ad780513c65465abe6c0bf956482e4d6b18697202e64841a055b75dc44e4a`
- `vault_backup_tree_sha256`: `da1e4bce5e2aca722da8e5c68fbd8a2bc9a27eb31aa0fd776c80b5c528c88e05`

Der erste Wert bindet das verifizierte Dateimanifest der Vault-Quelle. Der zweite Wert bindet den vollständigen bestehenden Backupbaum einschließlich seiner Manifestdateien. Die Werte haben unterschiedliche Bedeutung und wurden nicht gleichgesetzt oder überschrieben.

## Notwendige Nutzerentscheidungen

Vor genau einem späteren finalen Legacy-Backupversuch sind ausdrücklich zu bestätigen:

1. `state/models` bleibt vollständig metadata-only; eine spätere Konfigurations-Allowlist ist ein eigener Review.
2. Runtime-Caches einschließlich `.cache`, Hugging-Face-Downloads und Piper-Caches werden nur metadata-only inventarisiert und nicht kopiert.
3. Der Content-Backup wird als atomarer Archivcontainer mit SHA-256-Manifest geplant; ein kurzes Staging-Ziel dient ausschließlich der Restore-Probe.
4. Skills und Workflows bleiben untrusted metadata und werden nicht registriert oder aktiviert.

## Aussage zu einem finalen Versuch

Die Policy-Simulation ist **bestanden**: Es existiert kein unbekannter Pfad, kein migrationsrelevanter Langpfad und kein technischer oder sensitiver Content-Leak. Genau ein finaler Legacy-Backupversuch wäre nach ausdrücklicher Bestätigung der vier Entscheidungen technisch sicher planbar. Dieser Auftrag erteilt diese Freigabe nicht.

Phase 8A bleibt gestoppt. Phase 8B, Migration, Cutover und Vault-Writes wurden nicht begonnen.
