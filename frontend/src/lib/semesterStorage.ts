const STORAGE_PREFIX = "syllabus-calendar-semester-id"

function storageKey(userId: string) {
  return `${STORAGE_PREFIX}:${userId}`
}

export function getStoredSemester(userId: string) {
  return localStorage.getItem(storageKey(userId))
}

export function setStoredSemester(userId: string, semesterId: string) {
  localStorage.setItem(storageKey(userId), semesterId)
}

export function clearStoredSemester(userId: string) {
  localStorage.removeItem(storageKey(userId))
}
