# Core Video Analysis Acceptance - 2026-10-21

## Release Decision

V10 observation candidates are **not accepted for production**. The live V9
application, four school accounts, existing results and source videos have not
been replaced by these candidates. No UI redesign has been deployed in this run.

Engineering regression is not recognition accuracy. The latest cloud regression
of the candidate code completed with 893 passed and three pre-existing Python
escape warnings. Separate real-image review found contradictory actions.

## Reproducible Findings

The approved sample course 111 was used. Exact identifiers, source hashes and
unmasked images remain in private acceptance artifacts, not this document.

| Candidate | Actual result | Decision |
| --- | --- | --- |
| D, grayscale indexed proposals | 8 samples, 24 actions, 15 localized | Incorrect/unclear raised-hand and actor associations; rejected |
| E, higher-resolution color | One request timed out; three responses captured | No complete result published |
| F, color and bounded timeout retry | 8 samples, 23 localized actions; model stage 104.191 s | At least seven clear action contradictions; rejected |
| GLM comparison, two selected failure images | Six observations; 86.291 s | Selected sitting/standing errors corrected; not a general accuracy test |
| G, full GLM comparison | Invalid response schema; some returned samples empty | Rejected, no published replacement |
| Qwen comparison, two images | Request timeout | Not accepted |
| Context-crop comparison | Request timeout | Not accepted |
| Separate target crops, short prompt, flash model | Four pre-referenced targets; three literal matches, one clear standing actor reported seated | Rejected for general use; no published replacement |
| Same frozen child/foreground-actor crops, GLM comparison | One call, 33.932 s; both targets returned unknown/unsuitable | No incorrect seated claim, but no successful identification; rejected |

Both generated-image negative controls returned no observations, including a
control with decoy person-region coordinates. This does **not** prove correct
recognition on real classroom scenes or establish the provider's implementation.

Examples of F contradictions: sample 307 s reports seated people as standing;
sample 615 s reports a seated wall-side person as standing; sample 923 s reports
a foreground standing person as seated. Independent review recorded seven
explicit contradictions across the eight private contact sheets. No aggregate
accuracy statistic is claimed without a labelled evaluation set.

## Implemented Candidate Repairs

- Indexed local face proposals map back to server-owned coordinates, instead of
  asking the model to reproduce floating-point boxes.
- Original evidence stays immutable. Bounded color extraction records source,
  derived-image and actual model-input hashes, with explicit fallback reasons.
- Independently sought color frames cannot inherit an old frame's student
  identity. Confirmed identity frames keep their exact original evidence.
- An additive input-audit table is atomically linked to the stored result.
- Overlapping teacher/student regions block automatic and explicit attribution.
- The worker has a shared model-call deadline and at most one timeout retry per
  batch. Invalid schemas are rejected, not converted into normal observations.
- New still-frame model outputs cannot claim walking or leaving a seat. Old
  canonical records remain readable.
- Candidate refresh retains the previous ready result until a validated,
  compare-and-swap publication; reviewed input manifests must still match.
- Model timeouts, transport errors, rejected responses and invalid output now
  retain their separate bounded error codes in the candidate job record rather
  than collapsing into a generic failure. Reopening the store preserves the
  cause; raw provider text and credentials are not included.
- New automatically sampled jobs prioritize confirmed frames of the selected
  students, reserving coverage for each before filling the eight-frame budget.
  Explicit frame selections and existing ready jobs remain unchanged. This
  prevents earlier non-target bindings from excluding a later selected child;
  it does not solve cross-frame identity tracking or refresh an old result.

## Separate-Target Crop Check

Four small body crops were labelled from the source before inference. Each
crop used a frame-local head anchor and a short posture/hand-position prompt;
no names, diagnoses, IEP text or continuous identity were sent. The two requests
used the existing configured provider and flash model, taking 42.207 s and
40.738 s. They were not video-upload or full-processing timing measurements.

Two seated controls and one standing child candidate matched the fixed visible
reference. The fourth, a clearly standing foreground actor, was still reported
as seated. All returned hands-below-shoulder observations matched these four
references, but no positive raised-hand case was included. These selected cases
are not a population accuracy estimate, nor evidence of classroom attention,
learning mastery or a teaching score. Original crops, references and responses
remain private, and neither the default model nor live result was changed.

The follow-up changed only the requested model to GLM for the exact same two
standing-target crops and short prompt. It returned unknown for both in 33.932 s.
Abstention is distinct from a wrong posture, but does not satisfy the requested
recognition task. There was one call, no retry and no further model switching.

## Current Verification Boundary

The target-selection store tests passed 90 cases locally and the worker tests
passed 68. The combined cloud candidate regression passed 893 tests in 293.81 s.
An independent read-only code review found no concrete defect in these two
bounded changes. These are engineering checks, not a replacement for the failed
real-image comparisons above. No production code, result, account, source video,
student record, invitation or service was replaced in this work.

## Local Pose Cross-Check

An isolated MediaPipe PoseLandmarker full/lite experiment performed 14 local
inferences. It did not send classroom images to another provider or change the
live application's dependencies. Three whole-scene images, three manually
selected child-candidate regions and one adult control were inspected with both
models. Inputs were the 960x540 source half of private review contact sheets,
not a new original-resolution video benchmark.

The maroon-top candidate had plausible upper-body points. Both variants missed
the white-top person at the desk. A mustard-top candidate had a skeleton, but
the models' left-wrist estimates differed by 20.8 input pixels near another
person. These results do not validate automatic gesture classification or
whole-class child coverage. The experiment remains private and is not deployed.

## Remaining Product Blockers

1. Reliable person/action recognition has not passed real-video acceptance.
2. Anonymous face location is not a verified child identity or continuous track.
3. Ready observations cannot yet be recomputed through the UI after identity or
   target changes; this needs a versioned retry retaining earlier results/links.
4. External model use remains restricted to the four explicitly approved video
   hashes. Other uploaded school videos are not silently sent to the relay.
5. Eight point samples cannot establish whole-lesson percentages, durations,
   learning mastery, psychological attention or an educational grade.
6. Real named-student/IEP/video linkage still requires correct initial identity
   and authorization; test fixtures are not evidence of real identity accuracy.

## Next Acceptance Gate

Use the same positive/negative cases to test actor-focused vision and independent
local pose evidence. Review actual pixels and the exact reported action/actor,
not only HTTP success or valid rectangles. Preserve an unknown state for
occlusion or ambiguity. Do not publish a new result or change the default model
until this gate passes. Preserve manager-added workflows throughout.
