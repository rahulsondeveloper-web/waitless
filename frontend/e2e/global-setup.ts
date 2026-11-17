import { execFileSync } from 'node:child_process';
import path from 'node:path';

/**
 * Ensures the two demo restaurants (Urban Bites, Restaurant Remelle) exist in the dev database.
 * Idempotent: existing ones are skipped. The backend refuses this command in production.
 */
export default function globalSetup(): void {
  const backend = path.resolve(__dirname, '..', '..', 'backend');
  const python = path.join(backend, '.venv', 'Scripts', 'python.exe');
  const out = execFileSync(python, ['-m', 'app.cli', 'seed-demo'], { cwd: backend, encoding: 'utf-8' });
  process.stdout.write(out);
}
