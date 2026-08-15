import { mkdirSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join, resolve } from "node:path"
import { execFileSync } from "node:child_process"

import { assertFileMissing, assertRunRoot, keepProcessAlive, spawnManaged, terminateProcessTree, waitForUrl } from "./server-helpers.mjs"

const here = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(here, "..")
const workspaceRoot = resolve(frontendRoot, "..")
const backendRoot = join(workspaceRoot, "backend")
const runRoot = assertRunRoot()
const databasePath = join(runRoot, "syllabus-calendar-e2e.sqlite3")
const uploadsPath = join(runRoot, "uploads")
const pythonPath = process.platform === "win32"
  ? join(backendRoot, ".venv", "Scripts", "python.exe")
  : join(backendRoot, ".venv", "bin", "python")

mkdirSync(uploadsPath, { recursive: true })
assertFileMissing(databasePath)

const child = spawnManaged(
  pythonPath,
  ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010"],
  {
    cwd: backendRoot,
    env: {
      ...process.env,
      APP_ENV: "test",
      AUTH_MODE: "dev",
      PROCESSING_MODE: "eager",
      EXTRACTION_MODE: "local",
      CELERY_TASK_ALWAYS_EAGER: "true",
      DATABASE_URL: `sqlite:///${databasePath.replaceAll("\\", "/")}`,
      LOCAL_STORAGE_PATH: uploadsPath,
      CORS_ORIGINS: "http://127.0.0.1:5180",
      OPENAI_API_KEY: "",
    },
  },
)

await waitForUrl("http://127.0.0.1:8010/api/health")

execFileSync(
  pythonPath,
  [
    "-c",
    [
      "import sqlite3, sys",
      `db_path = r'''${databasePath}'''`,
      "connection = sqlite3.connect(db_path)",
      "cursor = connection.cursor()",
      "tables = ['semesters', 'syllabus_documents', 'extracted_events']",
      "counts = [cursor.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] for table in tables]",
      "connection.close()",
      "assert counts == [0, 0, 0], counts",
    ].join("; "),
  ],
  { cwd: backendRoot, stdio: "ignore" },
)

keepProcessAlive(() => terminateProcessTree(child))
