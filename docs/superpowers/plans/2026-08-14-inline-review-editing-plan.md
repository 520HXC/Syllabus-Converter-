# Inline review editing implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the always open Review event form with a compact summary card and an inline Modify editor that keeps the user on the same route.

**Architecture:** `ReviewEventCard` owns local expanded state and draft values. The compact state contains review evidence and decisions. The inline editor reuses the existing `onSave` callback, sends the current review status for plain edits, and keeps advanced fields behind progressive disclosure. `ReviewPage` passes a focused state for deep linked events, while `RecurringSeriesCard` continues to reuse the same child event component.

**Tech Stack:** React, TypeScript, Tailwind CSS, Testing Library, Vitest, Playwright

---

### Task 1: Compact card and inline editor tests

**Files:**
- Modify: `frontend/src/components/ReviewEventCard.test.tsx`
- Test: `frontend/src/components/ReviewEventCard.test.tsx`

- [ ] **Step 1: Write the failing compact state test**

Add a test that renders `ReviewEventCard` and asserts that the summary contains the event title, suggested date, syllabus quote, source page, warning, and `Modify`. Assert that `Event name`, `Event date`, `Save changes`, and `Guess is right` are absent before Modify is selected.

```tsx
test("shows a compact summary before modification", () => {
  render(<ReviewEventCard event={event} onSave={vi.fn()} {...defaultProps} />)

  expect(screen.getByRole("heading", { name: "Final project" })).toBeInTheDocument()
  expect(screen.getByText("December 10, 2026")).toBeInTheDocument()
  expect(screen.getByText(/Final project due around December 10/)).toBeInTheDocument()
  expect(screen.getByText("Page 5")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Modify Final project" })).toHaveAttribute(
    "aria-expanded",
    "false",
  )
  expect(screen.queryByLabelText("Event name")).not.toBeInTheDocument()
  expect(screen.queryByLabelText("Event date")).not.toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Guess is right" })).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Write the failing inline save and cancel tests**

The save test opens Modify, edits the title and date, selects Save changes, and verifies that the payload keeps `review_status` equal to the event's current status. The cancel test edits draft values, selects Cancel, reopens Modify, and verifies that saved values are restored and focus returns to Modify.

```tsx
test("modifies the title and date inline without changing review status", async () => {
  const user = userEvent.setup()
  const onSave = vi.fn().mockResolvedValue(undefined)
  render(<ReviewEventCard event={event} onSave={onSave} {...defaultProps} />)

  await user.click(screen.getByRole("button", { name: "Modify Final project" }))
  await user.clear(screen.getByLabelText("Event name"))
  await user.type(screen.getByLabelText("Event name"), "Final presentation")
  await user.clear(screen.getByLabelText("Event date"))
  await user.type(screen.getByLabelText("Event date"), "2026-12-12")
  await user.click(screen.getByRole("button", { name: "Save changes" }))

  expect(onSave).toHaveBeenCalledWith("event-1", expect.objectContaining({
    title: "Final presentation",
    event_date: "2026-12-12",
    review_status: "needs_review",
  }))
})
```

- [ ] **Step 3: Write the failing progressive disclosure test**

Open Modify and assert that `Event type`, `Start time`, and `End time` remain hidden until `More options` is selected. Confirm that all day state still controls the time fields.

- [ ] **Step 4: Run the focused tests and verify RED**

Run

```powershell
npm test -- --run src/components/ReviewEventCard.test.tsx
```

Expected result is failure because the current card renders all fields immediately and has no Modify state.

---

### Task 2: Implement compact ReviewEventCard

**Files:**
- Modify: `frontend/src/components/ReviewEventCard.tsx`
- Test: `frontend/src/components/ReviewEventCard.test.tsx`

- [ ] **Step 1: Add editor state and draft reset behavior**

Add `isEditing`, `showMoreOptions`, and a Modify button ref. Reset draft values from the current event when the event changes. Cancel restores the current event values, closes both disclosure levels, and returns focus to Modify.

```tsx
const modifyButtonRef = useRef<HTMLButtonElement>(null)
const [isEditing, setIsEditing] = useState(false)
const [showMoreOptions, setShowMoreOptions] = useState(false)

function resetDraft() {
  setTitle(event.title)
  setEventType(event.event_type)
  setEventDate(event.event_date ?? "")
  setStartTime(formatTimeInputValue(event.start_time))
  setEndTime(formatTimeInputValue(event.end_time))
  setIsAllDay(event.is_all_day)
  setError(null)
}

function cancelEditing() {
  resetDraft()
  setIsEditing(false)
  setShowMoreOptions(false)
  requestAnimationFrame(() => modifyButtonRef.current?.focus())
}
```

- [ ] **Step 2: Separate plain save from review decisions**

Change `save` to accept the current status as a valid plain edit. Save changes sends all edited fields and `event.review_status`, then closes the editor only after the request succeeds. Confirm still blocks when the date is missing. Keep pending, Remove, and Restore keep current behavior.

```tsx
async function save(reviewStatus: ReviewStatus, closeEditor = false) {
  if (reviewStatus === "confirmed" && !eventDate) {
    setError("Add a date before confirming this event.")
    setErrorTarget("date")
    setIsEditing(true)
    requestAnimationFrame(() => eventDateRef.current?.focus())
    return
  }

  await onSave(event.id, {
    title,
    event_type: eventType.trim() || event.event_type,
    event_date: eventDate || null,
    start_time: isAllDay ? null : normalizeTimeValue(startTime),
    end_time: isAllDay ? null : normalizeTimeValue(endTime),
    is_all_day: isAllDay,
    review_status: reviewStatus,
  })

  if (closeEditor) {
    setIsEditing(false)
    setShowMoreOptions(false)
    requestAnimationFrame(() => modifyButtonRef.current?.focus())
  }
}
```

- [ ] **Step 3: Render the compact evidence layout**

Keep course, status, confidence, model, warning, source quote, source page, suggested date, and derivation summary visible. Remove the two large AI summary panels and the always open form. Use a single compact evidence row that can wrap on narrow screens.

- [ ] **Step 4: Render the inline editor only when Modify is open**

The first row contains labeled name and date fields. `More options` reveals event type, all day, start time, and end time. Add Save changes and Cancel with loading, disabled, focus, and error states.

- [ ] **Step 5: Keep review decisions outside the editor**

Render Confirm, Keep pending, Remove, and Restore in a stable action row. Add Modify before review decisions for nonremoved events. Do not render `Guess is right` anywhere.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run

```powershell
npm test -- --run src/components/ReviewEventCard.test.tsx
```

Expected result is all ReviewEventCard tests passing.

---

### Task 3: Deep link opening and recurring child reuse

**Files:**
- Modify: `frontend/src/components/ReviewEventCard.tsx`
- Modify: `frontend/src/components/RecurringSeriesCard.tsx`
- Modify: `frontend/src/pages/ReviewPage.tsx`
- Modify: `frontend/src/pages/ReviewPage.test.tsx`
- Test: `frontend/src/pages/ReviewPage.test.tsx`

- [ ] **Step 1: Write the failing deep link test**

Open Review with `eventId=event-1` and assert that the correct document is selected, the card is visible, and `Event name` and `Event date` are open inside that card without changing the Review URL.

- [ ] **Step 2: Add a focused editing prop**

Add `startEditing?: boolean` to `ReviewEventCard`. When it changes to true, open Modify and focus the date field for date warnings or the title field otherwise.

```tsx
useEffect(() => {
  if (!startEditing) return
  setIsEditing(true)
  requestAnimationFrame(() => {
    if (attentionTarget === "date") eventDateRef.current?.focus()
    else titleRef.current?.focus()
  })
}, [attentionTarget, startEditing])
```

- [ ] **Step 3: Pass the focused state through ReviewPage and RecurringSeriesCard**

Standalone cards receive `startEditing={pendingFocusEventId === event.id}`. A recurring series passes its `focusEventId` to the matching child card. Keep the current document selection, reviewed group expansion, removed group expansion, and scroll behavior.

- [ ] **Step 4: Run ReviewPage and component tests**

Run

```powershell
npm test -- --run src/components/ReviewEventCard.test.tsx src/pages/ReviewPage.test.tsx
```

Expected result is both test files passing.

---

### Task 4: Browser coverage and final verification

**Files:**
- Modify: `frontend/e2e/mvp.spec.ts`
- Test: `frontend/e2e/mvp.spec.ts`

- [ ] **Step 1: Add the Playwright inline edit scenario**

In the isolated review flow, capture the current Review URL, select Modify on a needs review event, edit the name and date, save, and assert that the URL did not change. Assert that `Guess is right` does not exist and the compact card closes after saving.

- [ ] **Step 2: Add responsive overflow assertions**

At 375 pixels verify that document width is no greater than viewport width, actions remain visible, and the sticky footer does not cover the last card. Repeat the core card check in Dark mode.

- [ ] **Step 3: Run complete verification**

Run

```powershell
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e
```

Expected result is zero failures.

- [ ] **Step 4: Inspect the real local app**

Use the local app on port 5175. Check Review on desktop and 375 pixel mobile width in Light and Dark. Confirm summary density, Modify behavior, focus return, warning visibility, no horizontal overflow, and no console errors.
