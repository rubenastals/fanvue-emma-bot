// Cursor agent runner for the self-repair pipeline.
// Usage: node run_fix.mjs <prompt-file>
// Env: CURSOR_API_KEY (required), FIX_REPO (repo path, default cwd)
import { Agent, CursorAgentError } from "@cursor/sdk";
import { readFileSync } from "node:fs";

const promptFile = process.argv[2];
if (!promptFile) {
  console.error("STARTUP_ERROR:missing prompt file arg");
  process.exit(1);
}
const prompt = readFileSync(promptFile, "utf-8");
const apiKey = process.env.CURSOR_API_KEY;
if (!apiKey) {
  console.error("STARTUP_ERROR:CURSOR_API_KEY not set");
  process.exit(1);
}

try {
  const result = await Agent.prompt(prompt, {
    apiKey,
    model: { id: "composer-2.5" },
    local: { cwd: process.env.FIX_REPO || process.cwd() },
  });
  console.log("STATUS:" + result.status);
  console.log(result.result ?? "");
  process.exit(result.status === "finished" ? 0 : 2);
} catch (err) {
  if (err instanceof CursorAgentError) {
    console.error("STARTUP_ERROR:" + err.message);
    process.exit(1);
  }
  throw err;
}
