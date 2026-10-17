"""Hardware-free wake-to-window checks; no models, files, microphone or network."""
import importlib.util
from pathlib import Path
import threading
import unittest

spec = importlib.util.spec_from_file_location('wake_desktop', Path(__file__).resolve().parents[1] / 'scripts/wake-desktop.py')
wake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wake)


class Stream:
    def __init__(self, stop, frames, events):
        self.stop, self.frames, self.events = stop, iter(frames), events
    def __enter__(self):
        self.events.append('open')
        return self
    def __exit__(self, *args):
        self.events.append('closed')
    def read(self, count):
        assert count == 1280
        try:
            value = next(self.frames)
        except StopIteration:
            self.stop.set()
            value = False
        if isinstance(value, Exception): raise value
        return bytes(2560), value


class WakeContract(unittest.TestCase):
    def run_case(self, scores, times, frames=None):
        stop = threading.Event()
        events = []
        model = type('Model', (), {})()
        score_iter = iter(scores)
        model.predict = lambda _: next(score_iter, {'hey_jarvis': 0})
        model.reset = lambda: events.append('reset')
        stream = Stream(stop, frames or [False] * len(scores), events)
        def factory(**kwargs):
            self.assertEqual(kwargs, dict(samplerate=16000, channels=1, dtype='int16', blocksize=1280))
            return stream
        clock = iter(times)
        wake.listen(model, factory, stop, clock=lambda: next(clock, 100), emit=lambda marker, **_: events.append(marker))
        return events

    def test_warmup_ignores_even_high_scores_and_closes_before_wake(self):
        events = self.run_case([{'hey_jarvis': .99}, {'hey_jarvis': .46}], [0, 1, 3])
        self.assertEqual(events, ['open', 'ready', 'closed', 'wake'])

    def test_scores_below_fixed_threshold_do_not_wake(self):
        events = self.run_case([{'hey_jarvis': .44}], [0, 3])
        self.assertNotIn('wake', events)
        self.assertEqual(events[-1], 'closed')

    def test_other_model_score_is_ignored(self):
        events = self.run_case([{'another_model': .99}], [0, 3])
        self.assertNotIn('wake', events)

    def test_versioned_stock_score_key_is_supported(self):
        events = self.run_case([{'hey_jarvis_v0.1': .45}], [0, 3])
        self.assertEqual(events[-2:], ['closed', 'wake'])

    def test_overflow_discards_frame_and_resets_model(self):
        events = self.run_case([{'hey_jarvis': .46}], [0, 3], [True, False])
        self.assertEqual(events, ['open', 'reset', 'ready', 'closed', 'wake'])

    def test_capture_failure_still_releases_microphone(self):
        stop = threading.Event()
        events = []
        stream = Stream(stop, [OSError('synthetic')], events)
        with self.assertRaises(OSError):
            wake.listen(None, lambda **_: stream, stop)
        self.assertEqual(events, ['open', 'closed'])


if __name__ == '__main__': unittest.main()
