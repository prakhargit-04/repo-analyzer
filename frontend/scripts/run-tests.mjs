import { readdirSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const projectRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const testRoot = resolve(projectRoot, "src", "__tests__");

function collectTestFiles(directory) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectTestFiles(path));
    } else if (entry.isFile() && /\.test\.tsx?$/.test(entry.name)) {
      files.push(path);
    }
  }
  return files;
}

let testFiles;
try {
  testFiles = collectTestFiles(testRoot).sort();
} catch (error) {
  console.error(`Could not discover frontend tests under ${testRoot}: ${error.message}`);
  process.exit(1);
}

if (testFiles.length === 0) {
  console.error(`No frontend test files found under ${testRoot}`);
  process.exit(1);
}

const result = spawnSync(
  process.execPath,
  ["--import", "tsx", "--test", ...testFiles],
  { cwd: projectRoot, stdio: "inherit" },
);

if (result.error) {
  console.error(`Failed to start Node test runner: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status ?? 1);
