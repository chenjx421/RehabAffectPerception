# 《From Answers to Actions》国际学校双语 PPT 与生图提示词

## 1. Course Overview

- **English title:** From Answers to Actions
- **中文标题：** 从会回答到会行动
- **Subtitle:** An Introduction to Artificial Intelligence and Embodied AI
- **Case study:** Assistive Robots for Education and Rehabilitation
- **Audience:** International high school students
- **Duration:** 90 minutes
- **Recommended length:** 24 slides

## 2. Language Rules

整套课程采用“英文术语为主，中文解释为辅”的方式。

### Professional Terms

| English term | 中文解释 |
| --- | --- |
| Artificial Intelligence, AI | 人工智能 |
| Embodied AI | 具身智能 |
| Input | 输入 |
| Model | 模型 |
| Output | 输出 |
| Training | 训练 |
| Inference | 推理 |
| Confidence Score | 置信度 |
| Sensor | 传感器 |
| Actuator | 执行器 |
| Feedback Loop | 反馈闭环 |
| Image Classification | 图像分类 |
| Object Detection | 物体检测 |
| Pose Estimation | 姿态估计 |
| Automatic Speech Recognition, ASR | 自动语音识别 |
| Multimodal Perception | 多模态感知 |
| Multimodal Fusion | 多模态融合 |
| Human State | 人的交互状态 |
| Assistive Robot | 助残/辅助机器人 |
| Rehabilitation Robot | 康复机器人 |
| Safety Escalation | 安全升级处理 |
| Human-in-the-loop | 人在回路中的确认 |

### Slide Language

1. 页面主标题优先使用英文，下一行用较小中文解释。
2. 流程图、模块图、模型输出、按钮和专业标签使用英文。
3. 案例对话可以使用中文，方便现场讨论。
4. 不在同一行堆叠过多中英文。
5. 生图时优先让模型生成英文标签，中文长句后期在 PowerPoint 中添加。

## 3. Master Image-generation Prompt

每次生图时，先发送这段总提示词，再附上对应页面提示词。

```text
Create one 16:9 widescreen presentation slide for an international high-school course titled “From Answers to Actions: An Introduction to Artificial Intelligence and Embodied AI.”

The deck uses assistive robots for education and rehabilitation as its main case study.

Audience and tone:
- International high-school students aged approximately 15-18.
- Intellectually engaging and scientifically accurate.
- Modern and accessible, but not childish, cartoonish, overly corporate, or university-research dense.

Language system:
- Use English for professional terms, diagram labels, system modules, model outputs, and process steps.
- A short Chinese subtitle or explanation may appear below the English title.
- Do not generate long Chinese paragraphs.
- If Chinese text cannot be rendered accurately, leave a clean text area instead of generating garbled characters.

Visual system:
- 1920×1080, 16:9 landscape.
- White or very light cool-gray background.
- Dark charcoal text.
- Medium blue as the main accent.
- Limited orange for interaction, uncertainty, warnings, and robot actions.
- Use clean scientific infographics, credible assistive-robot scenes, simple engineering diagrams, or polished educational 3D illustrations.
- Use generous whitespace and one dominant visual idea per slide.
- Avoid neon cyberpunk, glowing brains, floating AI heads, circuit-board backgrounds, gradient blobs, excessive cards, and decorative technology clichés.
- Robots should look practical, safe, friendly, and physically plausible.
- Students should look like high-school students, not young children.
- Assistive scenarios must be respectful and must not portray disability as tragedy.

Layout rules:
- Keep a consistent title position and page-number system.
- Use no more than 3-5 short on-screen points.
- Keep all text unobstructed.
- Do not invent logos or brand marks.
- Do not add text that was not specified in the page prompt.
- Preserve clear space for manually adding Chinese explanations in PowerPoint.
```

## 4. Slide Structure

| Section | Slides | Time | Main Concepts |
| --- | --- | --- | --- |
| Opening Question | 1-3 | 0-10 min | Evidence, uncertainty, human state |
| AI Fundamentals | 4-6 | 10-22 min | Input, model, output, training, inference |
| Embodied AI | 7-11 | 22-38 min | Sensors, actuators, feedback loop |
| Robot Perception | 12-16 | 38-55 min | Vision, speech, multimodal fusion |
| Assistive Robotics | 17-19 | 55-65 min | Human state, actions, safety |
| Student Challenge | 20-23 | 65-85 min | System design and evaluation |
| Closing | 24 | 85-90 min | Responsible embodied AI |

## 5. Slide-by-slide Prompts

### Slide 1 — Cover

**English title**

```text
From Answers to Actions
```

**Chinese subtitle**

```text
从会回答到会行动
```

**Supporting text**

```text
An Introduction to Artificial Intelligence and Embodied AI
Case Study: Assistive Robots
```

**Prompt**

```text
Create the cover slide.

Place a practical modern assistive robot in a bright international-school innovation lab. The robot is interacting with a high-school student. Visible hardware should include a camera, microphone, speaker, and wheeled base. Keep the robot on the right and reserve generous title space on the left.

Text:
“From Answers to Actions”
“从会回答到会行动”
“An Introduction to Artificial Intelligence and Embodied AI”
“Case Study: Assistive Robots”

The image should communicate that AI is moving from digital conversation into physical action. Avoid humanoid battle robots, medical drama, holographic brains, and childish illustrations.
```

---

### Slide 2 — Opening Poll

**Title**

```text
What Should the Robot Trust?
机器人应该相信什么？
```

**Case**

```text
“I’m fine.”

But the student is looking down,
speaking softly, and not responding.
```

**Options**

```text
A. Words
B. Facial and body cues
C. Keep observing and ask
```

**Prompt**

```text
Create an interactive opening-poll slide.

On the left, show a high-school student sitting at a desk, looking down with a withdrawn posture but without exaggerated sadness. On the right, show a small assistive robot observing respectfully from a safe distance.

Between them, show three evidence channels:
1. A speech bubble: “I’m fine.”
2. A quiet audio waveform.
3. A simplified downward head-and-body posture cue.

Title:
“What Should the Robot Trust?”

Chinese subtitle:
“机器人应该相信什么？”

Options:
“A. Words”
“B. Facial and body cues”
“C. Keep observing and ask”

This should look like a serious classroom discussion, not an emotion-reading advertisement.
```

---

### Slide 3 — Evidence Is Not Truth

**Title**

```text
One Cue Is Not a Conclusion
一个线索，不等于一个结论
```

**Labels**

```text
Language
Voice
Facial Cues
Body Motion
Task Behaviour
```

**Output**

```text
Possible Human State
```

**Prompt**

```text
Create a multimodal-evidence infographic.

Place an assistive robot in the centre. Five evidence streams connect into the robot:
“Language”
“Voice”
“Facial Cues”
“Body Motion”
“Task Behaviour”

The robot produces an uncertain output labelled:
“Possible Human State”

Include a visible question mark or uncertainty indicator. Do not show the robot scanning a brain or reading thoughts.

Title:
“One Cue Is Not a Conclusion”

Chinese subtitle:
“一个线索，不等于一个结论”
```

---

### Slide 4 — AI Pipeline

**Title**

```text
How Does AI Make a Prediction?
人工智能怎样完成一次判断？
```

**Main flow**

```text
Input → Model → Output
```

**Labels**

```text
Images
Text
Audio
Sensor Data

Class
Location
Transcript
Action Suggestion
```

**Prompt**

```text
Create a clean three-stage horizontal AI pipeline.

Stage 1:
“Input”
Show images, text, an audio waveform, and sensor measurements.

Stage 2:
“Model”
Show a simple computational model module, not a glowing brain.

Stage 3:
“Output”
Show a predicted class, a bounding box, a transcript, and a robot action suggestion.

Main flow:
“Input → Model → Output”

Title:
“How Does AI Make a Prediction?”

Chinese subtitle:
“人工智能怎样完成一次判断？”

All diagram labels should be in English.
```

---

### Slide 5 — Training and Inference

**Title**

```text
Training Is Practice. Inference Is the Test.
训练像刷题，推理像考试
```

**Labels**

```text
Training
Learn patterns from many examples

Inference
Apply learned patterns to new input
```

**Prompt**

```text
Create a left-versus-right educational comparison.

Left side:
Label “Training”
Show many labelled examples entering a model.
Supporting line: “Learn patterns from many examples.”

Right side:
Label “Inference”
Show one previously unseen input entering the trained model and producing a prediction.
Supporting line: “Apply learned patterns to new input.”

Title:
“Training Is Practice. Inference Is the Test.”

Chinese subtitle:
“训练像刷题，推理像考试”

Use an academically mature visual metaphor appropriate for high-school students. Do not use a childish classroom cartoon.
```

---

### Slide 6 — Confidence and Error

**Title**

```text
92% Confident Does Not Mean 100% Correct
有把握，不代表一定正确
```

**Factors**

```text
Lighting
Camera Angle
Noise
Data Differences
```

**Conclusion**

```text
High-impact decisions need human confirmation.
```

**Prompt**

```text
Create a slide explaining AI uncertainty.

Use one robot-vision example shown under three conditions:
1. Clear lighting and unobstructed view.
2. Low light.
3. Partial occlusion.

Show a “92% Confidence” indicator, while making it clear that the prediction can still be wrong.

Factors:
“Lighting”
“Camera Angle”
“Noise”
“Data Differences”

Title:
“92% Confident Does Not Mean 100% Correct”

Chinese subtitle:
“有把握，不代表一定正确”

Bottom conclusion:
“High-impact decisions need human confirmation.”
```

---

### Slide 7 — Conversational AI vs Embodied AI

**Title**

```text
Answering Is Not the Same as Acting
会回答，不等于会行动
```

**Comparison**

```text
Conversational AI
Text In → Text Out

Embodied AI
Sense → Decide → Act → Adapt
```

**Prompt**

```text
Create a visual comparison between conversational AI and embodied AI.

Left:
A laptop with a text conversation interface.
Label:
“Conversational AI”
“Text In → Text Out”

Right:
A practical wheeled assistive robot with camera, microphone, distance sensor, speaker, and motors.
Label:
“Embodied AI”
“Sense → Decide → Act → Adapt”

Title:
“Answering Is Not the Same as Acting”

Chinese subtitle:
“会回答，不等于会行动”

Make the consequence difference visually clear: the robot physically affects the environment.
```

---

### Slide 8 — Robot Anatomy

**Title**

```text
How Does a Robot Sense and Act?
机器人怎样感知和行动？
```

**Labels**

```text
Camera — Vision
Microphone — Audio
Distance Sensor — Range
Model — Decision
Wheels — Motion
Speaker — Response
```

**Prompt**

```text
Create a clean technical anatomy illustration of a modern assistive robot.

Use callout lines to label:
“Camera — Vision”
“Microphone — Audio”
“Distance Sensor — Range”
“Model — Decision”
“Wheels — Motion”
“Speaker — Response”

Title:
“How Does a Robot Sense and Act?”

Chinese subtitle:
“机器人怎样感知和行动？”

The robot must be physically plausible and safe-looking. Use English for all technical labels.
```

---

### Slide 9 — Feedback Loop

**Title**

```text
The Embodied AI Feedback Loop
具身智能反馈闭环
```

**Flow**

```text
Sense → Decide → Act → Observe the Result
```

**Prompt**

```text
Create a four-stage circular feedback-loop diagram.

Stages:
“Sense”
Show camera and sensors.

“Decide”
Show model analysis.

“Act”
Show the robot moving or speaking.

“Observe the Result”
Show the environment and human response changing.

Connect the stages in a clear clockwise loop.

Title:
“The Embodied AI Feedback Loop”

Chinese subtitle:
“具身智能反馈闭环”

Supporting sentence:
“Every action changes what the robot observes next.”

All process labels should be in English.
```

---

### Slide 10 — Live Demonstration

**Title**

```text
Live Demo: Obstacle Avoidance
现场演示：机器人避障
```

**Questions**

```text
1. What did the robot sense?
2. How did it make a decision?
3. What action did it take?
```

**Prompt**

```text
Create a live-experiment instruction slide.

Show a small educational robot car moving toward a cardboard obstacle on a simple classroom floor course.

Use three numbered labels:
“1. Measure Distance”
“2. Compare with Safety Threshold”
“3. Stop or Turn”

Title:
“Live Demo: Obstacle Avoidance”

Chinese subtitle:
“现场演示：机器人避障”

Right-side questions:
“What did the robot sense?”
“How did it make a decision?”
“What action did it take?”

The slide should resemble a high-school engineering-lab activity.
```

---

### Slide 11 — Rule-based Control

**Title**

```text
Obstacle Avoidance Is a Decision Chain
避障是一条判断链
```

**Flow**

```text
Measure Distance
→ Compare Threshold
→ Change Motor Command
```

**Prompt**

```text
Create a simple engineering decision chain for obstacle avoidance.

Show:
“Distance = 35 cm”
→
“Distance < Safety Threshold?”
→
“STOP”
→
“TURN”

Title:
“Obstacle Avoidance Is a Decision Chain”

Chinese subtitle:
“避障是一条判断链”

Bottom formula:
“Measure Distance → Compare Threshold → Change Motor Command”

Use English labels and show a clear conditional decision. Avoid decorative code backgrounds.
```

---

### Slide 12 — Computer Vision Tasks

**Title**

```text
One Image, Different Questions
同一张画面，不同的视觉任务
```

**Columns**

```text
Image Classification
What is in the image?

Object Detection
What and where?

Pose Estimation
How is the body moving?
```

**Prompt**

```text
Create a three-column comparison using the same international-school classroom image.

Column 1:
“Image Classification”
Output: “Classroom”

Column 2:
“Object Detection”
Draw bounding boxes around “Person”, “Chair”, and “Backpack”.

Column 3:
“Pose Estimation”
Overlay shoulder, elbow, wrist, hip, and knee keypoints on the student.

Title:
“One Image, Different Questions”

Chinese subtitle:
“同一张画面，不同的视觉任务”

The difference among the three computer-vision tasks must be immediately understandable.
```

---

### Slide 13 — Object Detection

**Title**

```text
Object Detection: What and Where?
物体检测：是什么，在哪里？
```

**Labels**

```text
Person
Chair
Wheelchair
Obstacle
Rehabilitation Equipment
```

**Prompt**

```text
Create an object-detection example from the viewpoint of an assistive robot in a bright school rehabilitation room.

Show a student, chair, wheelchair, cardboard obstacle, and simple rehabilitation equipment.

Use clean bounding boxes labelled:
“Person”
“Chair”
“Wheelchair”
“Obstacle”
“Rehabilitation Equipment”

Title:
“Object Detection: What and Where?”

Chinese subtitle:
“物体检测：是什么，在哪里？”

Bottom note:
“The robot needs object location, not only object names.”
```

---

### Slide 14 — Pose Estimation

**Title**

```text
Pose Estimation Turns Motion into Keypoints
姿态估计把动作转化为关键点
```

**Questions**

```text
Was the arm raised?
Did movement speed decrease?
Is the posture stable?
```

**Prompt**

```text
Create a pose-estimation teaching slide.

Show the same high-school student in three consecutive stages of raising an arm. Overlay a clean human skeleton with shoulder, elbow, wrist, hip, and knee keypoints.

Title:
“Pose Estimation Turns Motion into Keypoints”

Chinese subtitle:
“姿态估计把动作转化为关键点”

Questions:
“Was the arm raised?”
“Did movement speed decrease?”
“Is the posture stable?”

Bottom note:
“Movement cues are not emotional truth.”
```

---

### Slide 15 — Speech Recognition

**Title**

```text
Speech Must Be Transcribed Before It Can Be Analysed
机器人先听清，才能进一步理解
```

**Flow**

```text
Audio → ASR Transcript → Possible State Cue
```

**Examples**

```text
“I don’t understand.” → Confusion cue
“I’m tired.” → Fatigue cue
“It hurts.” → Safety cue
```

**Prompt**

```text
Create an Automatic Speech Recognition workflow.

Left:
An audio waveform.

Middle:
Label “ASR Transcript”.
Show:
“I don’t understand.”
“I’m tired.”
“It hurts.”

Right:
“Confusion Cue”
“Fatigue Cue”
“Safety Cue”

Title:
“Speech Must Be Transcribed Before It Can Be Analysed”

Chinese subtitle:
“机器人先听清，才能进一步理解”

Main flow:
“Audio → ASR Transcript → Possible State Cue”

Bottom note:
“ASR can also make mistakes.”
```

---

### Slide 16 — Multimodal Fusion

**Title**

```text
Multiple Cues Make a Stronger Case
多个线索让判断更可靠
```

**Evidence**

```text
Speech: “I’m tired.”
Pose: Movement slowed
Task: Response delay increased
History: Repeated failures
```

**Output**

```text
Possible State: Fatigue
Robot Question: “Would you like a short break?”
```

**Prompt**

```text
Create a multimodal-fusion case-study slide.

On the left, show four evidence streams:
“Speech: I’m tired.”
“Pose: Movement slowed”
“Task: Response delay increased”
“History: Repeated failures”

Connect them into a central module labelled:
“Multimodal Fusion”

On the right, show:
“Possible State: Fatigue”
“Confidence: Higher”

Robot confirmation:
“Would you like a short break?”

Title:
“Multiple Cues Make a Stronger Case”

Chinese subtitle:
“多个线索让判断更可靠”

Do not show the output as a medical or emotional diagnosis.
```

---

### Slide 17 — Assistive Robot Definition

**Title**

```text
Assistive Robots Support People — They Do Not Replace Them
助残机器人辅助人，而不是替代人
```

**Functions**

```text
Learning Support
Rehabilitation Guidance
Safety Reminders
Caregiver Notification
```

**Prompt**

```text
Create an assistive-robot application slide showing one coherent school environment rather than four separate business cards.

In the same scene, show the robot:
- Providing step-by-step learning support.
- Guiding a simple rehabilitation movement.
- Stopping near an obstacle.
- Sending a notification to a teacher.

Use four labels:
“Learning Support”
“Rehabilitation Guidance”
“Safety Reminders”
“Caregiver Notification”

Title:
“Assistive Robots Support People — They Do Not Replace Them”

Chinese subtitle:
“助残机器人辅助人，而不是替代人”

Keep the teacher and student as the decision-makers.
```

---

### Slide 18 — Ambiguous Human State

**Title**

```text
The Same Sentence Can Mean Different Things
同一句话，可能对应不同问题
```

**Dialogue**

```text
“I can’t do this. I don’t want to continue.”
```

**Possible explanations**

```text
Confusion
Task Too Difficult
Fatigue
Frustration
Physical Discomfort
```

**Prompt**

```text
Create a case-analysis slide.

At the centre, show a high-school student at a learning or rehabilitation task saying:
“I can’t do this. I don’t want to continue.”

Branch outward to five possible explanations:
“Confusion”
“Task Too Difficult”
“Fatigue”
“Frustration”
“Physical Discomfort”

Title:
“The Same Sentence Can Mean Different Things”

Chinese subtitle:
“同一句话，可能对应不同问题”

Bottom question:
“What should the robot do next?”

The student should look age-appropriate and realistic, not childish or dramatically distressed.
```

---

### Slide 19 — Safety Escalation

**Title**

```text
Higher Risk Requires More Conservative Action
风险越高，机器人越应该保守
```

**Levels**

```text
Level 1 — Support
Explain, simplify, encourage

Level 2 — Pause and Confirm
Stop approaching, offer a break, ask

Level 3 — Safety Escalation
Stop motion, notify a teacher or caregiver
```

**Prompt**

```text
Create a three-level safety-escalation staircase.

Level 1 in blue:
“Support”
“Confusion / Low Attention”
“Explain, Simplify, Encourage”

Level 2 in orange:
“Pause and Confirm”
“Fatigue / Frustration”
“Offer a Break, Keep Distance, Ask”

Level 3 in restrained red:
“Safety Escalation”
“Pain / Help Request / Fall Risk”
“Stop Motion, Notify Teacher or Caregiver”

Title:
“Higher Risk Requires More Conservative Action”

Chinese subtitle:
“风险越高，机器人越应该保守”
```

---

### Slide 20 — Design Challenge

**Title**

```text
Design Challenge: Build a Human-State Response Module
设计挑战：构建人的状态响应模块
```

**Constraints**

```text
The robot may sense, listen, and record task events.
It may not touch the student.
It may not make a medical diagnosis.
It must define when a human takes over.
```

**Prompt**

```text
Create a high-school engineering-design challenge slide.

Show four international high-school students working as a product-and-engineering team around a table containing a small assistive robot, camera, microphone, task-log screen, and system sketch.

Title:
“Design Challenge: Build a Human-State Response Module”

Chinese subtitle:
“设计挑战：构建人的状态响应模块”

Constraints:
“May sense, listen, and record task events”
“May not touch the student”
“May not make a medical diagnosis”
“Must define human takeover conditions”

Bottom line:
“You are the product and engineering team.”
```

---

### Slide 21 — Scenario Selection

**Title**

```text
Choose One Scenario
选择一个场景
```

**Scenarios**

```text
A. Repeated failure: “I don’t understand.”
B. “Do not come closer.” The student steps back.
C. Movement slows: “I’m tired.”
D. The student suddenly says: “It hurts.”
E. The student looks away and stops responding.
```

**Prompt**

```text
Create a scenario-selection slide using five horizontal numbered rows, not childish cards.

Title:
“Choose One Scenario”

Chinese subtitle:
“选择一个场景”

Rows:
“A. Repeated failure: I don’t understand.”
“B. Do not come closer. The student steps back.”
“C. Movement slows: I’m tired.”
“D. The student suddenly says: It hurts.”
“E. The student looks away and stops responding.”

Add one restrained line illustration to each scenario. Keep the page highly readable on a classroom projector.
```

---

### Slide 22 — System Design Canvas

**Title**

```text
Your System Must Answer Six Questions
你们的系统必须回答六个问题
```

**Canvas**

```text
1. Sensor Inputs
2. Model Outputs
3. Possible Human State
4. Robot Action
5. Human Takeover
6. Evaluation Metric
```

**Prompt**

```text
Create an engineering system-design canvas appropriate for international high-school students.

Title:
“Your System Must Answer Six Questions”

Chinese subtitle:
“你们的系统必须回答六个问题”

Six clearly numbered areas:
“1. Sensor Inputs”
“2. Model Outputs”
“3. Possible Human State”
“4. Robot Action”
“5. Human Takeover”
“6. Evaluation Metric”

Add one central process:
“Input → Perception → Decision → Action → Safety → Evaluation”

Use black and white with blue numbering. Leave generous blank space so the structure can also be recreated as a printable worksheet.
```

---

### Slide 23 — Presentation and Review

**Title**

```text
Explain One Critical Design Decision
只讲一个最关键的设计决定
```

**Criteria**

```text
Clarity
Feasibility
Respect
Safety
```

**Question**

```text
What happens if the robot is wrong?
```

**Prompt**

```text
Create a high-school innovation-review slide.

On the left, show a student team presenting a robot-system diagram for one minute.

On the right, show four review criteria:
“Clarity”
“Feasibility”
“Respect”
“Safety”

Title:
“Explain One Critical Design Decision”

Chinese subtitle:
“只讲一个最关键的设计决定”

Bottom review question:
“What happens if the robot is wrong?”

The atmosphere should resemble an engineering design review, not a children's talent show.
```

---

### Slide 24 — Closing

**Title**

```text
Useful Robots Need More Than Intelligence
真正有用的机器人，不只需要聪明
```

**Conclusion**

```text
Intelligent
Safe
Conservative
Respectful
```

**Review**

```text
AI: Input → Model → Output
Embodied AI: Sense → Decide → Act → Adapt
Assistive Robotics: Support People, Do Not Replace Them
```

**Exit question**

```text
What should future robots learn first?
```

**Prompt**

```text
Create the closing slide.

Show the same assistive robot, high-school students, and teacher from the earlier slides in a bright innovation classroom. The robot is in a supporting position while humans remain central.

Title:
“Useful Robots Need More Than Intelligence”

Chinese subtitle:
“真正有用的机器人，不只需要聪明”

Four keywords:
“Intelligent”
“Safe”
“Conservative”
“Respectful”

Review:
“AI: Input → Model → Output”
“Embodied AI: Sense → Decide → Act → Adapt”
“Assistive Robotics: Support People, Do Not Replace Them”

Bottom question:
“What should future robots learn first?”

Use a warm but rational ending. Avoid sentimental medical imagery.
```

## 6. Classroom Materials

### Required

| Item | Quantity | Purpose |
| --- | ---: | --- |
| Presenter laptop | 1 | Slides and demo |
| HDMI adapters | 1-2 | Display compatibility |
| Presentation clicker | 1 | Timing and movement |
| Educational robot car | 1 | Obstacle-avoidance demo |
| Cardboard boxes or books | 2-3 | Obstacles |
| Floor tape | 1 roll | Demo boundary |
| Scenario cards | 1 per team | Design challenge |
| A3 System Design Canvas | 1 per team | Team output |
| Black markers | 2 per team | Writing |
| Timer | 1 | Discussion and presentation |

### Recommended

| Item | Purpose |
| --- | --- |
| Webcam | Optional perception demo |
| External speaker | Speech examples |
| Microphone | Large classroom interaction |
| Coloured voting stickers | Opening poll |
| Spare battery or power bank | Robot-car backup |
| Pre-recorded robot demo | Hardware-failure backup |
| Offline slides and videos | Network-failure backup |

## 7. Printable Team Canvas

```text
TEAM:
SCENARIO:

1. SENSOR INPUTS
What information does the robot collect?

2. MODEL OUTPUTS
What does the AI system detect or predict?

3. POSSIBLE HUMAN STATE
What might be happening? How confident are you?

4. ROBOT ACTION
What should the robot say or do?

5. HUMAN TAKEOVER
When must a teacher or caregiver intervene?

6. EVALUATION METRIC
How will you know the design is useful and safe?

FAILURE CASE
What could the robot misunderstand?
```

## 8. Image-generation Workflow

1. 首先把 Master Image-generation Prompt 发给 GPT。
2. 每次只生成一页，并附上该页的独立提示词。
3. 要求所有专业标签使用英文。
4. 中文副标题建议后期在 PowerPoint 中人工添加。
5. 第 1 页生成后，可以把封面图作为后续页面的人物和机器人参考图。
6. 第 10、13、14、17、18、20 和 24 页应要求延续同一机器人造型。
7. 流程图和设计画布优先使用英文，因为生图模型生成英文标签通常更稳定。
8. 第 4、9、11、12、16、19 和 22 页最好在 PowerPoint 中使用形状重新绘制，以保证文字正确并可编辑。
