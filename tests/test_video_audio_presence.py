"""CPU regression tests; no ComfyUI installation, model weights or GPU needed.

Run: python -m unittest discover -s tests -p 'test_video_audio_presence.py' -v
Requires numpy and torch. PyAV is replaced with a deterministic decoder fixture.
"""
import ast
import builtins
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import numpy as np
import torch


def load_audio_function():
    # Avoid importing unrelated ComfyUI/custom-node dependencies during CPU tests.
    source = Path(__file__).resolve().parents[1] / 'nodes_video.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    function = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == '_lazy_get_audio')
    scope = {'np': np, 'torch': torch}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), scope)
    return scope['_lazy_get_audio']


class Container:
    def __init__(self, has_audio=True, frames=(), error=None):
        stream = types.SimpleNamespace(type='audio',
                                       codec_context=types.SimpleNamespace(sample_rate=32000))
        self.streams = [stream] if has_audio else []
        self.frames, self.error = frames, error
        self.closed = False
        self.decode_calls = 0

    def decode(self, stream):
        self.decode_calls += 1
        if self.error is not None:
            raise self.error
        return iter(self.frames)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def frame(values):
    return types.SimpleNamespace(pts=0, to_ndarray=lambda: values)


class AudioPresenceTests(unittest.TestCase):
    def setUp(self):
        self.get_audio = load_audio_function()
        self.containers = []
        self.open_error = None
        self.open_calls = 0
        def opening(_):
            self.open_calls += 1
            if self.open_error is not None:
                raise self.open_error
            return self.containers.pop(0)
        self.fake_av = types.SimpleNamespace(open=opening)
        patcher = patch.dict(sys.modules, {'av': self.fake_av})
        patcher.start()
        self.addCleanup(patcher.stop)

    # What: absent stream is None. Red if the (1,1) placeholder is restored.
    def test_absent_stream_returns_none_and_closes_probe(self):
        probe = Container(has_audio=False)
        self.containers = [probe]
        self.assertIsNone(self.get_audio('synthetic.mp4'))
        self.assertTrue(probe.closed)
        self.assertEqual(probe.decode_calls, 0)

    # What: decoding is lazy/cached; normal samples unchanged. Red on eager decode or lost cache.
    def test_valid_audio_is_lazy_cached_and_unchanged(self):
        values = np.array([[0.0, .25, -.25, 0.0]], dtype=np.float32)
        probe, decoder = Container(), Container(frames=[frame(values)])
        self.containers = [probe, decoder]
        audio = self.get_audio('synthetic.mp4')
        self.assertEqual(self.open_calls, 1)
        self.assertEqual(decoder.decode_calls, 0)
        actual = audio['waveform']
        self.assertEqual(tuple(actual.shape), (1, 1, 4))
        torch.testing.assert_close(actual, torch.from_numpy(values).unsqueeze(0))
        self.assertIs(audio['waveform'], actual)
        self.assertEqual(audio['sample_rate'], 32000)
        self.assertEqual(self.open_calls, 2)
        self.assertTrue(probe.closed and decoder.closed)

    # What: true silence is still audio. Red if zero-valued samples mean "no stream".
    def test_real_silence_is_not_absent_audio(self):
        self.containers = [Container(), Container(frames=[frame(np.zeros((1, 1600), np.float32))])]
        audio = self.get_audio('synthetic.mp4')
        self.assertIsNotNone(audio)
        self.assertEqual(tuple(audio['waveform'].shape), (1, 1, 1600))

    # What: empty decode fails, not fake silence. Red if the fallback tensor is restored.
    def test_empty_decode_raises_and_closes(self):
        decoder = Container()
        self.containers = [Container(), decoder]
        with self.assertRaises(RuntimeError) as caught:
            self.get_audio('synthetic.mp4')['waveform']
        self.assertIsInstance(caught.exception.__cause__, ValueError)
        self.assertTrue(decoder.closed)

    # What: decoded zero-length arrays fail. Red if only the frame list is checked.
    def test_zero_sample_frame_raises(self):
        decoder = Container(frames=[frame(np.empty((1, 0), np.float32))])
        self.containers = [Container(), decoder]
        with self.assertRaises(RuntimeError) as caught:
            self.get_audio('synthetic.mp4')['waveform']
        self.assertIn('no decoded samples', str(caught.exception.__cause__))
        self.assertTrue(decoder.closed)

    # What: decoder failure keeps its cause and closes. Red on catch-all fallback.
    def test_decode_failure_preserves_cause(self):
        failure = ValueError('synthetic decoder failure')
        decoder = Container(error=failure)
        self.containers = [Container(), decoder]
        with self.assertRaises(RuntimeError) as caught:
            self.get_audio('synthetic.mp4')['waveform']
        self.assertIs(caught.exception.__cause__, failure)
        self.assertTrue(decoder.closed)

    # What: unreadable input is an error. Red if it is treated like a missing audio stream.
    def test_probe_failure_preserves_cause(self):
        self.open_error = OSError('synthetic unreadable container')
        with self.assertRaises(RuntimeError) as caught:
            self.get_audio('synthetic.mp4')
        self.assertIs(caught.exception.__cause__, self.open_error)

    # What: missing dependency is actionable. Red if _Dummy returns a tensor for every key.
    def test_missing_pyav_raises(self):
        original = builtins.__import__
        def importing(name, *args, **kwargs):
            if name == 'av':
                raise ImportError('synthetic missing PyAV')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=importing):
            with self.assertRaisesRegex(RuntimeError, 'PyAV'):
                self.get_audio('synthetic.mp4')

    # What: disappearance between probe/decode fails. Red if converted to fake silence.
    def test_stream_disappearing_after_probe_is_an_error(self):
        decoder = Container(has_audio=False)
        self.containers = [Container(), decoder]
        with self.assertRaises(RuntimeError):
            self.get_audio('synthetic.mp4')['waveform']
        self.assertTrue(decoder.closed)


if __name__ == '__main__':
    unittest.main()
