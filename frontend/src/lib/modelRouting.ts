function humanizeReasonCode(code: string) {
  return code
    .toLowerCase()
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

export function formatFallbackReasons(codes: string[]) {
  const labels = codes.map(humanizeReasonCode)
  if (!labels.length) return null
  if (labels.length === 1) return labels[0]
  return `${labels.slice(0, -1).join(", ")} and ${labels.at(-1)}`
}
