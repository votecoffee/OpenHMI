import unittest
from fastapi.testclient import TestClient
from openhmi.drivers import SimulatorDriver
from openhmi.server import create_app


class SimulatorTests(unittest.TestCase):
    def test_read_write_and_snapshot_isolation(self):
        driver = SimulatorDriver()
        driver.write('TankLevel', [17.5])
        self.assertEqual(driver.read('TankLevel'), [17.5])
        driver.snapshot()['TankLevel'] = 99.0
        self.assertEqual(driver.read('TankLevel'), [17.5])

    def test_unknown_addresses_and_invalid_writes_do_not_create_tags(self):
        driver = SimulatorDriver()
        with self.assertRaises(KeyError):
            driver.write('Unknown', [1.0])
        for values in ([1], [True], [], [1.0, 2.0], [float('nan')], [float('inf')]):
            with self.assertRaises(ValueError):
                driver.write('TankLevel', values)
        self.assertEqual(driver.read('TankLevel'), [42.0])
        with self.assertRaises(ValueError):
            driver.read('TankLevel', 2)

    def test_app_state_isolated_and_api_read_only(self):
        app = create_app()
        other = create_app()
        app.state.driver.write('MotorRunning', [False])
        with TestClient(app) as client, TestClient(other) as second:
            self.assertFalse(client.get('/api/tags').json()['values']['MotorRunning'])
            self.assertTrue(second.get('/api/tags').json()['values']['MotorRunning'])
            self.assertEqual(client.post('/api/tags', json={}).status_code, 405)
            self.assertEqual(client.get('/').status_code, 200)
            self.assertEqual(client.get('/static/vendor/grapes.min.js').status_code, 200)


if __name__ == '__main__':
    unittest.main()
