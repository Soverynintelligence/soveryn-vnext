/**
 * JIT 2-strike bash retry for house OpenCode (Jon 2026-09-12).
 * Default OFF. Enable with JIT_TOOL_RETRY=1 or KERNEL_TOOL_RETRY=1.
 * On bash tool failure: short backoff, re-run same command once, replace output.
 * Does not patch soveryn-pi. Logs to JIT_RETRY_LOG JSONL when set.
 */
import { spawnSync } from "node:child_process"
import { appendFileSync, mkdirSync } from "node:fs"
import { dirname } from "node:path"

function enabled() {
  const v = process.env.JIT_TOOL_RETRY || process.env.KERNEL_TOOL_RETRY || "0"
  return v === "1" || v === "2" || v.toLowerCase() === "true"
}

function cmdFromArgs(args) {
  if (!args || typeof args !== "object") return null
  return args.command || args.cmd || args.script || null
}

function looksFailed(output) {
  if (output?.metadata?.error) return true
  if (output?.metadata?.exit != null && Number(output.metadata.exit) !== 0) return true
  if (output?.metadata?.exitCode != null && Number(output.metadata.exitCode) !== 0) return true
  const s = String(output?.output || "")
  if (/^Error:/i.test(s)) return true
  // common bash failure markers from OpenCode
  if (/exit code[: ]+[1-9]/i.test(s)) return true
  if (/Command failed/i.test(s)) return true
  return false
}

function logRetry(rec) {
  const p = process.env.JIT_RETRY_LOG
  if (!p) return
  try {
    mkdirSync(dirname(p), { recursive: true })
    appendFileSync(p, JSON.stringify(rec) + "\n")
  } catch {}
}

const seen = new Set() // callID already retried

export const JitToolRetryPlugin = async () => {
  if (!enabled()) {
    return {}
  }
  return {
    "tool.execute.after": async (input, output) => {
      const tool = input?.tool || ""
      if (tool !== "bash" && tool !== "shell") return
      const callID = input?.callID || `${tool}:${JSON.stringify(input?.args||{}).slice(0,80)}`
      if (seen.has(callID)) return
      if (!looksFailed(output)) return
      const cmd = cmdFromArgs(input?.args)
      if (!cmd || typeof cmd !== "string") return

      seen.add(callID)
      const backoffMs = Number(process.env.JIT_RETRY_BACKOFF_MS || 200)
      spawnSync("sleep", [String(Math.max(0.05, backoffMs / 1000))], { encoding: "utf8" })

      const cwd = process.env.JIT_TASK_CWD || process.cwd()
      const r = spawnSync("bash", ["-lc", cmd], {
        encoding: "utf8",
        cwd,
        timeout: 60000,
        env: process.env,
      })
      const out = (r.stdout || "") + (r.stderr ? `\n${r.stderr}` : "")
      const ok = r.status === 0
      output.title = (output.title || "bash") + " (jit-retry)"
      output.output = ok
        ? `[jit-retry ok after 1 failure]\n${out}`
        : `[jit-retry still failed exit=${r.status}]\n${out}`
      output.metadata = {
        ...(output.metadata || {}),
        error: ok ? undefined : `jit-retry exit ${r.status}`,
        exit: r.status,
        exitCode: r.status,
        jit_retry: true,
        jit_retry_count: 1,
      }
      logRetry({
        ts: new Date().toISOString(),
        arm: process.env.JIT_ARM || "retry",
        task_id: process.env.JIT_TASK_ID || "unknown",
        tool,
        cmd: cmd.slice(0, 500),
        first_failed: true,
        retry_ok: ok,
        exit: r.status,
      })
    },
  }
}

export default JitToolRetryPlugin
