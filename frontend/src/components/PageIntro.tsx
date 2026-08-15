import { cn } from "../lib/utils"

export function PageIntro({
  eyebrow,
  title,
  description,
  className,
}: {
  eyebrow: string
  title: string
  description: string
  className?: string
}) {
  return (
    <div className={cn("mb-8 max-w-2xl", className)}>
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-text-subtle">{eyebrow}</p>
      <h1 className="mt-3 text-3xl font-bold tracking-[-0.04em] text-text sm:text-4xl">{title}</h1>
      <p className="mt-3 max-w-xl text-base leading-7 text-text-muted sm:text-[1.05rem]">{description}</p>
    </div>
  )
}
