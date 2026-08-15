import { fileURLToPath } from "node:url"
import { dirname, resolve } from "node:path"

import { keepProcessAlive, spawnManaged, terminateProcessTree, waitForUrl } from "./server-helpers.mjs"

const here = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(here, "..")
const viteCli = resolve(frontendRoot, "node_modules", "vite", "bin", "vite.js")

const child = spawnManaged(
  process.execPath,
  [viteCli, "--host", "127.0.0.1", "--port", "5180", "--strictPort"],
  {
    cwd: frontendRoot,
    env: {
      ...process.env,
      VITE_API_URL: "http://127.0.0.1:8010/api",
      VITE_AUTH_MODE: "demo",
    },
  },
)

await waitForUrl("http://127.0.0.1:5180")

keepProcessAlive(() => terminateProcessTree(child))
