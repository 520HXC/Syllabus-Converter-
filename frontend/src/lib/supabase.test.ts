import { describe, expect, it } from "vitest"

import { resolveAuthMode } from "./supabase"

describe("resolveAuthMode", () => {
  it("fails closed to Supabase when authentication mode is not configured", () => {
    expect(resolveAuthMode(undefined)).toBe("supabase")
  })

  it("allows demo mode only when it is explicitly configured", () => {
    expect(resolveAuthMode("demo")).toBe("demo")
  })
})
