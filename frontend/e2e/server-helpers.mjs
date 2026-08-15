import { execFileSync, spawn } from "node:child_process"
import { existsSync } from "node:fs"
import { setTimeout as delay } from "node:timers/promises"

export function assertRunRoot() {
  const runRoot = process.env.E2E_RUN_ROOT
  if (!runRoot) throw new Error("E2E_RUN_ROOT is required for isolated end to end runs.")
  return runRoot
}

export function spawnManaged(command, args, options) {
  const child = spawn(command, args, {
    ...options,
    stdio: "inherit",
  })
  child.on("exit", (code, signal) => {
    if (signal) process.exit(1)
    if (code && code !== 0) process.exit(code)
  })
  return child
}

export async function waitForUrl(url, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {}
    await delay(500)
  }
  throw new Error(`Timed out waiting for ${url}`)
}

export function terminateProcessTree(child) {
  if (!child?.pid) return
  try {
    if (process.platform === "win32") {
      execFileSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" })
      return
    }
    child.kill("SIGTERM")
  } catch {}
}

export function keepProcessAlive(cleanup) {
  let cleanedUp = false
  const stop = (code = 0) => {
    if (cleanedUp) return
    cleanedUp = true
    cleanup()
    process.exit(code)
  }

  process.on("SIGINT", () => stop(0))
  process.on("SIGTERM", () => stop(0))
  process.on("exit", () => {
    if (!cleanedUp) cleanup()
  })

  const timer = setInterval(() => {}, 60_000)
  timer.unref()
}

export function assertFileMissing(path) {
  if (existsSync(path)) throw new Error(`Expected isolated file to be absent before startup: ${path}`)
}
