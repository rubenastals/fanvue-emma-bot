// Cursor CLOUD agent for hourly quality review + code fix PR.
// Usage: node run_hour_review.mjs <prompt-file>
// Env: CURSOR_API_KEY (required)
//      HOUR_REVIEW_REPO_URL (default emma-fanvue-bot github)
//      HOUR_REVIEW_REF (default main)
//      HOUR_REVIEW_AUTO_PR (default 1)
//      HOUR_REVIEW_MODEL (default composer-2.5)
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

const repoUrl =
  process.env.HOUR_REVIEW_REPO_URL ||
  "https://github.com/rubenastals/fanvue-emma-bot";
const startingRef = process.env.HOUR_REVIEW_REF || "main";
const autoCreatePR = process.env.HOUR_REVIEW_AUTO_PR !== "0";
const modelId = process.env.HOUR_REVIEW_MODEL || "composer-2.5";
const stamp = new Date().toISOString().slice(0, 13).replace(/:/g, "");

try {
  const result = await Agent.prompt(prompt, {
    apiKey,
    name: `emma-hour-review-${stamp}`,
    model: { id: modelId },
    cloud: {
      repos: [{ url: repoUrl, startingRef }],
      autoCreatePR,
      skipReviewerRequest: true,
    },
  });
  console.log("STATUS:" + result.status);
  if (result.agentId) console.log("AGENT_ID:" + result.agentId);
  if (result.id) console.log("RUN_ID:" + result.id);
  console.log(result.result ?? "");
  // finished / expired with work still useful — non-zero only on hard fail
  process.exit(result.status === "finished" || result.status === "completed" ? 0 : 2);
} catch (err) {
  if (err instanceof CursorAgentError) {
    console.error("STARTUP_ERROR:" + err.message);
    process.exit(1);
  }
  throw err;
}
