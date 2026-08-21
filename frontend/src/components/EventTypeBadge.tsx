import type { HTMLAttributes } from "react"

import { getEventTypeBadgeClass, getEventTypeLabel } from "../lib/reviewBadges"
import { cn } from "../lib/utils"
import { Badge } from "./ui/Badge"

export function EventTypeBadge({
  className,
  eventType,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { eventType: string }) {
  const label = getEventTypeLabel(eventType)

  return (
    <Badge
      className={cn("border", getEventTypeBadgeClass(eventType), className)}
      data-event-type={label}
      {...props}
    >
      {label}
    </Badge>
  )
}
