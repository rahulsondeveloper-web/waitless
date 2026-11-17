import { execFileSync } from 'node:child_process';
import path from 'node:path';

/**
 * Ensures the test-only copies of the demo restaurants exist (e2e-urban-bites, e2e-remelle) and resets them,
 * so manual experiments on the real demos never break the tests. The backend refuses this in production.
 */
export default function globalSetup(): void {
  const backend = path.resolve(__dirname, '..', '..', 'backend');
  const python = path.join(backend, '.venv', 'Scripts', 'python.exe');
  const out = execFileSync(python, ['-m', 'app.cli', 'seed-demo', '--e2e'], { cwd: backend, encoding: 'utf-8' });
  process.stdout.write(out);
}
