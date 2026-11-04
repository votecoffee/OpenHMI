import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';

const python = fileURLToPath(new URL(process.platform === 'win32'
  ? './.venv/Scripts/python.exe' : './.venv/bin/python', import.meta.url));

export default defineConfig({
  testDir: './tests/browser',
  workers: 1,
  use: { channel: 'chrome', baseURL: 'http://127.0.0.1:8765', viewport: { width: 1440, height: 1000 } },
  webServer: {
    command: `"${python}" -m uvicorn tests.browser_server:create_test_app --factory --host 127.0.0.1 --port 8765`,
    url: 'http://127.0.0.1:8765/api/tags',
    reuseExistingServer: false,
  },
});
