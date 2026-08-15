# Inline review editing design

## Goal

Make the Review workspace easier to scan by showing a compact event summary first. Users can modify the event name and date inside the same card without changing routes.

## Default event card

Each event card shows only the information needed for a review decision

- Course label and course color
- Event title
- Confidence level and current review status
- Syllabus quote and source page
- AI suggested date
- Warning reason when attention is required
- Model label and fallback reason when available

The default card does not render editable fields. It does not include a `Guess is right` action.

The visible actions are

- `Modify`
- `Confirm`
- `Keep pending`
- `Remove`

Removed events keep the existing restore behavior.

## Inline modification

Selecting `Modify` expands an editor inside the same card. The route, selected PDF, scroll position, review group, and event identity stay unchanged.

The first editor view contains

- Event name
- Event date
- `Save changes`
- `Cancel`

`More options` reveals the existing event type, all day setting, start time, and end time fields. This keeps current functionality while removing it from the default view.

Saving changes uses the existing event update API and preserves the current review status. A user must still choose Confirm, Keep pending, or Remove as a separate review decision. Cancel restores the last saved values and closes the editor.

If a save fails, the editor stays open, the user's input remains, and the error appears next to the affected field or action area.

## Attention and source behavior

Warnings remain visible in the compact state. Date warnings highlight the date summary and the date input after Modify is opened. Source warnings highlight the quote and page area. Card warnings highlight the whole card with an icon and text so color is not the only signal.

An event opened through `eventId` deep linking stays on the same Review route. The correct PDF and event card open, the card scrolls into view, and Modify opens automatically when the event needs a name or date correction.

## Recurring series

The recurring series summary remains a series level decision. Expanding the generated dates shows compact child event cards. Selecting Modify on a child date opens the same inline editor used for standalone events.

Confirming a series continues to confirm every member that has not been removed. A removed member does not return when the series is confirmed.

## Responsive behavior

Desktop keeps the PDF and extracted details split view. Mobile keeps the PDF and Extracted details tabs.

Event actions wrap without horizontal overflow. Every touch target is at least 44 pixels high with at least 8 pixels between adjacent actions. The editor uses one column on small screens and two columns only when enough width is available.

Light, Dark, and System themes continue to use existing semantic tokens. Focus rings, loading states, disabled states, reduced motion, and keyboard operation remain available.

## Accessibility

- Modify exposes `aria-expanded`
- The inline editor has an accessible label tied to the event title
- Save errors use `role="alert"`
- Cancel returns focus to Modify
- Keyboard users can open, edit, save, cancel, and choose every review action
- Warning meaning always includes an icon and text

## Data and API impact

No backend route, database model, migration, or payload shape changes are required.

The existing event update endpoint saves edits. A plain Save changes request sends the edited event fields with the event's current review status. Confirm, Keep pending, Remove, and Restore keep their existing status payloads.

## Test coverage

Component tests prove

- Default cards do not render input fields
- No `Guess is right` action exists
- Modify opens the editor without navigation
- Save changes keeps the current review status
- Cancel restores saved values and focus
- More options preserves type and time editing
- Confirm still requires a date
- Remove and restore behavior remains intact
- Recurring child events use the compact card

Playwright proves

- Desktop Review stays within the viewport
- A 375 pixel viewport has no horizontal overflow
- Modify edits a name and date on the same Review URL
- Light and Dark remain readable
- A deep linked event opens the correct card and editor

## Out of scope

- A separate event editing route
- Autosaving every keystroke
- Backend or database changes
- Replacing the existing PDF viewer
- Rewriting recurring series rules
