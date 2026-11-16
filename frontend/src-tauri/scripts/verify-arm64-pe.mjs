// Fail packaging if an x64 executable was accidentally staged as ARM64.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

assert.ok(process.argv.length > 2, 'Pass at least one Windows executable');
for (const path of process.argv.slice(2)) {
  const bytes = readFileSync(path);
  assert.ok(bytes.length >= 64, `${path}: truncated DOS header`);
  assert.equal(bytes.toString('ascii', 0, 2), 'MZ', `${path}: missing DOS signature`);
  const offset = bytes.readUInt32LE(0x3c);
  assert.ok(offset + 6 <= bytes.length, `${path}: truncated PE header`);
  assert.equal(bytes.readUInt32LE(offset), 0x4550, `${path}: missing PE signature`);
  assert.equal(bytes.readUInt16LE(offset + 4), 0xaa64, `${path}: expected ARM64 machine type`);
  console.log(`Verified ARM64: ${path}`);
}
