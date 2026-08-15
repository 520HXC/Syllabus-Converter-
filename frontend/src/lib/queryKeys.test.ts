import { semesterQueryKey } from "./queryKeys"

test("scopes semester query data to the authenticated user", () => {
  expect(semesterQueryKey("user-a")).not.toEqual(semesterQueryKey("user-b"))
})
