# Phase 8A: vollständige Backup-Policy-Planung

Stand: 31. Juli 2026

## Entscheidung und Grenzen

Dieser Bericht dokumentiert ausschließlich den metadata-only Planungsmodus. Es wurde kein dritter Legacy-Backupversuch gestartet, kein Legacy-Backupziel erzeugt, kein Vault-Dry-Run begonnen und keine Phase-8B-Arbeit ausgeführt.

- Quellenlabel: `legacy-jarvis-desktop`
- Legacy-HEAD: `6a333806d184f7cf65ebad63dfee70cdbdcbddac`
- Legacy-Git-Status-Einträge: 157
- geplantes Ziellabel: `phase-8a-long-external-tree`
- erfasste Pfade: 18239
- Quelle über zwei Metadatenscans stabil: `true`
- Quelldateiinhalte geöffnet oder gehasht: `0`
- Copy- oder Netzwerkaufrufe: `0`

### Planrevision und Nachweis

- vorheriger Plan (unverändert erhalten), SHA-256: `22b43dfc7a599f7a2ad144408b7b2cb9dba1527b3aa178c0eb0f501144a7fe0e`
- korrigierter revisionsgebundener Plan, SHA-256: `1e4f096c9a85202230537f0f37d4567fd7e2eacc908cb329d46a28913e40f196`
- Ablösung: Der korrigierte Plan ersetzt den vorherigen Plan als operative Policy-Grundlage; die vorherige externe Datei wurde weder überschrieben noch gelöscht.
- Prohibited Roots werden nur als Root erfasst. Nachfahren werden weder inventarisiert noch in Dateinamen-, Größen- oder Erweiterungsstatistiken aufgenommen.

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
| `runtime_state_metadata_only` | 45 | 4921647 |
| `model_artifact_metadata_only` | 36 | 686059956 |
| `technical_cache_excluded` | 41 | 2282 |
| `build_artifact_excluded` | 17847 | 3275740075 |
| `credential_or_session_prohibited` | 2 | 13783 |
| `browser_runtime_prohibited` | 1 | 0 |
| `temporary_excluded` | 6 | 12460 |
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
| `.sqlite` | 11 |
| `.wav` | 11 |
| `.json` | 8 |
| `no_extension` | 8 |
| `.bak` | 7 |
| `.onnx` | 6 |
| `.log` | 5 |
| `.metadata` | 5 |
| `.tag` | 3 |
| `.tflite` | 3 |
| `.bin` | 1 |
| `.jsonl` | 1 |
| `.py` | 1 |
| `.pyc` | 1 |
| `.txt` | 1 |
| `.webm` | 1 |

## Langpfadanalyse

- Sicheres Windows-Ziellimit: 247
- Zielroot-Länge der bestehenden Variante: 116
- Pfade oberhalb des Limits: 31
- davon sicher ausgeschlossen/metadata-only: 31
- davon migrationsrelevant: 0
- davon unbekannt: 0
- maximal geplante Zielpfadlänge: 274
- Pfade bis 20 Zeichen unter dem Limit: 229
- Pfade mit Segmenten ab 80 Zeichen: 0
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
- nur als Root erfasste prohibited Verzeichnisse: 1
- inventarisierte Nachfahren prohibited Roots: 0
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
