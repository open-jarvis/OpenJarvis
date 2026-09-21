"""Eval output must record which hardware did the work, and how it was measured.

Before this, an eval result row carried only ``energy_joules`` and
``power_watts``. On Apple Silicon that hides the entire point of the
measurement: an ANE-resident model draws almost nothing on the GPU rail, so a
reader could not tell a Neural Engine run from an idle machine, nor a hardware
measurement from a modelled estimate. Both distinctions now have to survive
the trip from the monitor to the JSONL file.
"""

from __future__ import annotations

from openjarvis.evals.core.types import EvalResult


def _apple_result() -> EvalResult:
    """A result shaped like an AFM run: ANE-dominant, GPU near zero."""
    return EvalResult(
        record_id="r1",
        model_answer="ok",
        energy_joules=43.104,
        power_watts=4.69,
        cpu_energy_joules=27.851,
        gpu_energy_joules=0.670,
        dram_energy_joules=8.902,
        ane_energy_joules=5.681,
        soc_energy_joules=43.104,
        energy_basis="soc",
        energy_method="ioreport",
    )


class TestEvalResultCarriesRails:
    def test_rail_fields_exist_with_safe_defaults(self):
        r = EvalResult(record_id="r", model_answer="")
        for field in (
            "cpu_energy_joules",
            "gpu_energy_joules",
            "dram_energy_joules",
            "ane_energy_joules",
            "soc_energy_joules",
        ):
            assert getattr(r, field) == 0.0
        assert r.energy_basis == ""
        assert r.energy_method == ""

    def test_ane_is_distinguishable_from_gpu(self):
        """The claim the whole Apple path rests on.

        A GPU-only view of this run would report 0.67 J and look idle; the
        work actually happened on the Neural Engine.
        """
        r = _apple_result()
        assert r.ane_energy_joules > r.gpu_energy_joules * 8
        assert r.soc_energy_joules > r.gpu_energy_joules

    def test_method_separates_measurement_from_estimate(self):
        assert _apple_result().energy_method == "ioreport"
        estimated = EvalResult(
            record_id="r", model_answer="", energy_method="tdp_estimate"
        )
        assert estimated.energy_method != "ioreport"


class TestSerializedRow:
    def test_written_row_includes_rails_and_method(self):
        """Guards the JSONL schema itself.

        The runner builds result rows by hand, so a field can exist on
        EvalResult and still never reach the file — which is exactly how this
        gap arose.
        """
        import inspect

        from openjarvis.evals.core import runner as runner_mod

        source = inspect.getsource(runner_mod)
        for key in (
            '"ane_energy_joules": result.ane_energy_joules',
            '"soc_energy_joules": result.soc_energy_joules',
            '"energy_basis": result.energy_basis',
            '"energy_method": result.energy_method',
        ):
            assert key in source, f"result row no longer writes {key}"
