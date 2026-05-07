# Mining test fixtures

`gateway_metrics_sample.txt` is the expected Pearl gateway Prometheus shape.
The live 2026-05 H100 validation found that Pearl's current Docker miner exposes
vLLM metrics on `:8000/metrics`, while the gateway listens on `/tmp/pearlgw.sock`
and does not expose `:8339/metrics`. Keep this fixture as the target contract if
Pearl adds gateway metrics later. Re-capture by:

1. Run the Pearl Docker image on an H100 host per the spec §7.4 launch shape.
2. `curl http://127.0.0.1:8339/metrics > gateway_metrics_sample.txt` once
   the gateway exposes metrics and at least 10 shares have been submitted.
3. Strip any cardinality bombs (per-prompt or per-block-time histograms)
   that bloat the file.
4. Commit, citing the Pearl commit/tag the capture was taken against.

If Pearl renames metrics, update `mining/_metrics.py::PROM_*` constants and
re-capture.
