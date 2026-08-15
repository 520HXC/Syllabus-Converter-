import tailwindConfig from "../../tailwind.config"

import { expect, test } from "vitest"

test("keeps warning.DEFAULT mapped to the semantic CSS variable", () => {
  const colors = tailwindConfig.theme?.extend?.colors
  const warning = colors && "warning" in colors ? colors.warning : undefined

  expect(warning).toEqual(
    expect.objectContaining({
      DEFAULT: "rgb(var(--warning) / <alpha-value>)",
    }),
  )
})
