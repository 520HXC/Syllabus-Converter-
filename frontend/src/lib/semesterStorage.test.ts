import { clearStoredSemester, getStoredSemester, setStoredSemester } from "./semesterStorage"

describe("semester storage", () => {
  beforeEach(() => localStorage.clear())

  test("keeps the last semester separate for each user", () => {
    setStoredSemester("user-a", "semester-a")
    setStoredSemester("user-b", "semester-b")

    expect(getStoredSemester("user-a")).toBe("semester-a")
    expect(getStoredSemester("user-b")).toBe("semester-b")
  })

  test("clears only the signed-out user's semester", () => {
    setStoredSemester("user-a", "semester-a")
    setStoredSemester("user-b", "semester-b")

    clearStoredSemester("user-a")

    expect(getStoredSemester("user-a")).toBeNull()
    expect(getStoredSemester("user-b")).toBe("semester-b")
  })
})
