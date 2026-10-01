/**
 * ActTruth ledger for Kernel OpenCode tool acts.
 * Hooks tool.execute.after → scripts/acttruth_record_tool.py (agent=kernel).
 */
import { spawn } from "node:child_process"
import { homedir } from "node:os"
import { join } from "node:path"

const HOME = homedir()
const RECORDER = join(HOME, "soveryn_vnext", "scripts", "acttruth_record_tool.py")
const PYTHON =
  process.env.SOVERYN_PYTHON ||
  join(HOME, "miniconda3", "envs", "soveryn", "bin", "python")

function truncate(v, n = 4000) {
  const s = typeof v === "string" ? v : JSON.stringify(v ?? "")
  if (!s) return ""
  return s.length > n ? s.slice(0, n) + "…(truncated)" : s
}

function scrubArgs(args) {
  if (!args || typeof args !== "object") return { raw: truncate(args, 1000) }
  const out = {}
  for (const [k, v] of Object.entries(args)) {
    const key = String(k).toLowerCase()
    if (key.includes("password") || key.includes("token") || key.includes("secret") || key.includes("api_key")) {
      out[k] = "[redacted]"
      continue
    }
    if (typeof v === "string" && v.length > 2000) out[k] = truncate(v, 2000)
    else out[k] = v
  }
  return out
}

function record(payload) {
  return new Promise((resolve) => {
    try {
      const child = spawn(PYTHON, [RECORDER, "--stdin"], {
        stdio: ["pipe", "ignore", "ignore"],
        env: { ...process.env, ACTTRUTH_AGENT: "kernel" },
      })
      child.on("error", () => resolve(false))
      child.on("close", () => resolve(true))
      child.stdin.end(JSON.stringify(payload))
      setTimeout(() => {
        try { child.kill() } catch {}
        resolve(false)
      }, 5000)
    } catch {
      resolve(false)
    }
  })
}

export const ActTruthKernelPlugin = async ({ client }) => {
  try {
    await client?.app?.log?.({
      body: {
        service: "acttruth-kernel",
        level: "info",
        message: "ActTruth Kernel plugin loaded",
        extra: { recorder: RECORDER },
      },
    })
  } catch {
    /* ignore */
  }

  return {
    "tool.execute.after": async (input, output) => {
      const tool = input?.tool || "unknown"
      if (tool.startsWith("opencode.") || tool === "invalid") return

      const payload = {
        agent: "kernel",
        tool,
        args: scrubArgs(input?.args ?? output?.args),
        ok: true,
        result: truncate(output?.output ?? output?.title ?? "", 4000),
      }
      if (output?.metadata?.error) {
        payload.ok = false
        payload.error = truncate(output.metadata.error, 2000)
      } else if (typeof output?.output === "string" && /^Error:/i.test(output.output)) {
        payload.ok = false
        payload.error = truncate(output.output, 2000)
      }

      await record(payload)
    },
  }
}
