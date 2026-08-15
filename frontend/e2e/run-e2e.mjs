import { mkdtemp, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { basename, join, relative, resolve } from "node:path"
import { spawn } from "node:child_process"
import { fileURLToPath } from "node:url"

const runRoot = await mkdtemp(join(tmpdir(), "syllabus-calendar-e2e-"))
const frontendRoot = fileURLToPath(new URL("..", import.meta.url))
const playwrightCli = join(frontendRoot, "node_modules", "@playwright", "test", "cli.js")

try {
  const child = spawn(process.execPath, [playwrightCli, "test"], {
    cwd: frontendRoot,
    env: {
      ...process.env,
      E2E_RUN_ROOT: runRoot,
      PLAYWRIGHT_BASE_URL: "http://127.0.0.1:5180",
    },
    stdio: "inherit",
  })

  const exitCode = await new Promise((resolve, reject) => {
    child.on("error", reject)
    child.on("exit", (code) => resolve(code ?? 1))
  })
  process.exitCode = exitCode
} finally {
  const resolvedRunRoot = resolve(runRoot)
  const resolvedTmpRoot = resolve(tmpdir())
  const insideTmp = !relative(resolvedTmpRoot, resolvedRunRoot).startsWith("..")
  const safeName = basename(resolvedRunRoot).startsWith("syllabus-calendar-e2e-")
  if (!insideTmp || !safeName) {
    throw new Error(`Refusing to remove unexpected e2e directory: ${resolvedRunRoot}`)
  }
  await rm(resolvedRunRoot, { recursive: true, force: true })
}
