# Demo2 Page Rules

This file overrides the master design system only where Demo2 needs a specific behavior.

## Page Structure

1. Seven-step course confirmation gate.
2. Product header with course status and course selector.
3. Evidence workspace introduction and four-stage process.
4. Collapsible course and assessment baseline.
5. Full-width classroom video with group/portrait modes and student evidence pane.
6. Three-student selector.
7. Analysis workspace with four navigation groups and fourteen views.
8. Privacy and interpretation boundary.

## Signature Experience

The distinctive product interaction is the evidence chain:

`student signal -> teacher support -> student follow-up -> teacher review -> next action`

The UI must emphasize the relationship between these events, not produce a feed of isolated body movements.

## Course Gate

- Use a dark mineral left rail and white task pane.
- Ask one course question per step.
- Final confirmation names the responsible person and keeps the review boundary visible.
- Desktop uses a centered 1160px shell; mobile becomes a full-height single-column flow.

## Classroom Workbench

- The classroom image is the largest first-viewport evidence object.
- At `1120px` and below, the classroom stage uses a stable 16:9 ratio so the image fills the available width without cropping the evidence frame.
- Use professional users/user icons for group and portrait modes.
- The selected student exposes mastery, participation evidence, support action, and teacher-confirmation requirement.
- Do not place captions or controls over students' faces.

## Analysis Workspace

- Student cards remain a compact three-way selector, not KPI marketing cards.
- Desktop tab rail is sticky below the product header.
- Mobile tab scrolling changes only the tab rail; it must never move the entire page.
- Result summary contains mastery, participation, review count, and support effectiveness.

## Teacher Review

- Show the review guide, selected 30-second window, and timeline before clip forms.
- First evidence clip opens by default; other clips show ID, course/student, time, and review status.
- Each expanded clip retains six explicit teacher steps.
- “Uncertain” must remain available and must not be counted as failure or regression.
- CSV export stays visible in the review guide.

## Robot Action Display

- Display screen, speech, motion, and teacher-side behavior separately.
- Robot motion always shows a human-readable Chinese phrase followed by the internal policy code.
- High-impact actions explicitly require teacher confirmation.
- Avoid autonomous touching, fast approach, strong light, loud audio, or continuous prompting.

## QA Targets

- Desktop: `1440x1000`.
- School laptop: `1366x768`.
- School display / compact laptop: `1024x900`.
- Tablet: `768x900`.
- Mobile: `390x844`.
- Narrow mobile: `360x800`.
- Required screenshots: entry, workspace, profile, state timeline, interaction, review, support effect, mastery, support tools, action plan, growth, course report, deep report, source data, JSON, and mobile review/report.
