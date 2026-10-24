// Runs a Gridiron checkout's LP-record adapter on the frozen E2 envelope and, if given, the v1 document.
//
// Usage: node gridiron_adapter_proof.mjs <gridiron-root> <envelope.json> [v1-document.json]
//
// The Gridiron root is any checkout or `git archive` extraction of the repository; it is read, never written, and no
// package manager is run. Prints one JSON object with the adapter's verdict and the audit findings in full.
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const [root, envelopePath, v1Path] = process.argv.slice(2);
if (!root || !envelopePath) {
  console.error('usage: node gridiron_adapter_proof.mjs <gridiron-root> <envelope.json> [v1-document.json]');
  process.exit(2);
}
const adapter = await import(pathToFileURL(`${root}/web/lp-game-record-adapter.js`).href);
const payload = JSON.parse(await readFile(envelopePath, 'utf8'));
const out = { gridiron_root: root, envelope: envelopePath };
try {
  const a = adapter.adaptLpGamePayload(payload);
  out.adapter = {
    accepted: true,
    sourcePlayCount: a.sourcePlayCount,
    drives: a.drives.length,
    scores: a.record.points,
    validationPassed: a.validation.passed,
    validationFindings: a.validation.findings.length,
    footballStateFindings: a.footballStateAudit.finding_count,
    sharedV1Violations: a.sharedV1Audit.violations,
  };
} catch (error) {
  out.adapter = { accepted: false, error: error.message };
}
if (v1Path) {
  const doc = JSON.parse(await readFile(v1Path, 'utf8'));
  out.v1Document = { file: v1Path, violations: adapter.auditGridironContractV1Record(doc).violations };
}
console.log(JSON.stringify(out, null, 1));
