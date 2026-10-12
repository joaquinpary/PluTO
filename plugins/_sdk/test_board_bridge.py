import unittest
from unittest.mock import MagicMock

from pluto_sdk import ConfigurationError, from_environment
from pluto_sdk.board_bridge import BoardBridge

DEVICE_ID = 'a1b2c3d4e5f6'


class BoardBridgeTests(unittest.TestCase):
    def setUp(self):
        self.api = MagicMock()
        self.bridge = BoardBridge(DEVICE_ID, self.api)

    def test_subscribes_to_its_board_only(self):
        self.assertEqual(self.bridge.subscriptions(), [
            (f'device/{DEVICE_ID}/status', 1),
            (f'device/{DEVICE_ID}/state', 0),
        ])

    def test_handles_its_board_and_nothing_else(self):
        self.assertTrue(self.bridge.handles(f'device/{DEVICE_ID}/status'))
        self.assertTrue(self.bridge.handles(f'device/{DEVICE_ID}/state'))
        self.assertFalse(self.bridge.handles('device/0a0b0c0d0e0f/status'))
        self.assertFalse(self.bridge.handles(f'device/{DEVICE_ID}/coordinates/polar'))
        self.assertFalse(self.bridge.handles('pluto/My_TinyGS/rx'))

    def test_forwards_the_payload_untouched(self):
        self.bridge.forward(f'device/{DEVICE_ID}/status', b'offline')
        self.bridge.forward(f'device/{DEVICE_ID}/state', b'{"mode": "tracking"}')

        self.assertEqual(self.api.send_device.call_args_list[0].args, ('status', b'offline'))
        self.assertEqual(self.api.send_device.call_args_list[1].args, ('state', b'{"mode": "tracking"}'))

    def test_rejects_a_device_id_that_is_not_a_mac(self):
        for device_id in ('A1B2C3D4E5F6', 'a1:b2:c3:d4:e5:f6', '+', ''):
            with self.assertRaises(ValueError):
                BoardBridge(device_id, self.api)


class FromEnvironmentTests(unittest.TestCase):
    ENV = {'PLUTO_API_URL': 'http://server:8000/api/', 'PLUTO_API_TOKEN': 'pluto_secret'}

    def test_without_a_board_there_is_no_bridge(self):
        api, bridge = from_environment(dict(self.ENV))
        api.stop()

        self.assertEqual((api.base_url, api.token), ('http://server:8000/api/', 'pluto_secret'))
        self.assertIsNone(bridge)

    def test_with_a_board_the_bridge_uses_the_same_client(self):
        api, bridge = from_environment({**self.ENV, 'ROTOR_DEVICE_ID': DEVICE_ID})
        api.stop()

        self.assertIs(bridge.api, api)
        self.assertEqual(bridge.device_id, DEVICE_ID)

    def test_the_api_variables_are_required(self):
        with self.assertRaises(ConfigurationError):
            from_environment({'PLUTO_API_URL': 'http://server:8000/api/'})

    def test_a_malformed_board_id_is_a_configuration_error(self):
        with self.assertRaises(ConfigurationError):
            from_environment({**self.ENV, 'ROTOR_DEVICE_ID': 'not-a-mac'})


if __name__ == '__main__':
    unittest.main()
