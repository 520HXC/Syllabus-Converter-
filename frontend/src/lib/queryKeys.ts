export function semesterQueryKey(userId: string | undefined) {
  return ["semesters", userId] as const
}
