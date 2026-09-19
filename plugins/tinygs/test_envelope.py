import base64
import json
import unittest
from datetime import datetime, timezone

from envelope import MAX_PAYLOAD_BYTES, PREVIEW_BYTES, build_envelope, normalize_payload


class NormalizePayloadTests(unittest.TestCase):
    def test_json_object_passes_through(self):
        payload, fmt = normalize_payload(b'{"satellite": "NOAA-19", "freq": 137.1}')

        self.assertEqual(payload, {"satellite": "NOAA-19", "freq": 137.1})
        self.assertEqual(fmt, "json")

    def test_json_array_is_wrapped_in_items(self):
        payload, fmt = normalize_payload(b'[1, 2, 3]')

        self.assertEqual(payload, {"items": [1, 2, 3]})
        self.assertEqual(fmt, "json_array")

    def test_json_scalar_is_wrapped_in_value(self):
        for raw, expected in ((b'42', 42), (b'null', None), (b'"hola"', "hola"), (b'true', True)):
            payload, fmt = normalize_payload(raw)

            self.assertEqual(payload, {"value": expected})
            self.assertEqual(fmt, "json_scalar")

    def test_plain_text_is_wrapped_in_text(self):
        payload, fmt = normalize_payload(b'RSSI:-97 SNR:-3')

        self.assertEqual(payload, {"text": "RSSI:-97 SNR:-3"})
        self.assertEqual(fmt, "text")

    def test_binary_is_base64_encoded(self):
        raw = b'\x00\x01\xff\xfe'

        payload, fmt = normalize_payload(raw)

        self.assertEqual(fmt, "binary")
        self.assertEqual(base64.b64decode(payload["raw_base64"]), raw)
        self.assertEqual(payload["size"], 4)

    def test_oversized_payload_is_truncated(self):
        raw = b'x' * (MAX_PAYLOAD_BYTES + 1)

        payload, fmt = normalize_payload(raw)

        self.assertEqual(fmt, "truncated")
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["size"], MAX_PAYLOAD_BYTES + 1)
        self.assertEqual(len(base64.b64decode(payload["preview_base64"])), PREVIEW_BYTES)

    def test_result_is_always_a_dict(self):
        for raw in (b'{}', b'[]', b'42', b'texto', b'\xff', b'x' * (MAX_PAYLOAD_BYTES + 1)):
            payload, _ = normalize_payload(raw)

            self.assertIsInstance(payload, dict, msg=raw[:20])


class BuildEnvelopeTests(unittest.TestCase):
    def build(self, raw=b'{"az": 1}', **kwargs):
        defaults = dict(
            plugin_id="3f2a-uuid",
            plugin_type="tinygs",
            device="heltec-lp-01",
            message_type="tracking",
            source_topic="pluto/heltec-lp-01/tracking",
            raw=raw,
        )
        defaults.update(kwargs)
        return build_envelope(**defaults)

    def test_envelope_has_required_keys(self):
        envelope = self.build()

        for key in ('schema_version', 'message_id', 'plugin_id', 'plugin_type', 'device',
                    'message_type', 'source_topic', 'received_at', 'payload_format', 'payload'):
            self.assertIn(key, envelope)

    def test_envelope_is_json_serializable(self):
        self.assertIsInstance(json.dumps(self.build(raw=b'\xff\xfe')), str)

    def test_payload_is_always_a_dict(self):
        self.assertIsInstance(self.build(raw=b'42')["payload"], dict)

    def test_message_id_is_unique_per_call(self):
        self.assertNotEqual(self.build()["message_id"], self.build()["message_id"])

    def test_received_at_is_iso_utc(self):
        now = datetime(2026, 9, 12, 18, 3, 11, tzinfo=timezone.utc)

        envelope = self.build(now=now)

        self.assertEqual(envelope["received_at"], "2026-09-12T18:03:11+00:00")
        self.assertIsNotNone(datetime.fromisoformat(envelope["received_at"]).tzinfo)


if __name__ == "__main__":
    unittest.main()
