import importlib.util
import io
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('power_reader', Path(__file__).resolve().parents[1] / 'src/integrated/power-read.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


class PowerReaderTests(unittest.TestCase):
    def test_each_request_gets_a_new_read_and_eof_stops(self):
        calls = []
        def read():
            calls.append(1)
            return {'state': 'Active' if len(calls) == 1 else 'Suspend'}
        output = io.StringIO()
        reader.serve(io.StringIO('{"id":1}\n{"id":2}\n'), output, read)
        self.assertEqual(len(calls), 2)
        self.assertEqual(output.getvalue(), '{"id":1,"power":{"state":"Active"}}\n{"id":2,"power":{"state":"Suspend"}}\n')

    def test_invalid_requests_never_read_power(self):
        for raw in ('{}\n', '{"id":true}\n', '{"id":0}\n', '{"id":1,"method":"write"}\n', '{"id":1}', 'x' * 128):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    reader.serve(io.StringIO(raw), io.StringIO(), lambda: self.fail('Unexpected read'))

    def test_empty_input_has_no_automatic_requests(self):
        reader.serve(io.StringIO(''), io.StringIO(), lambda: self.fail('Unexpected read'))
