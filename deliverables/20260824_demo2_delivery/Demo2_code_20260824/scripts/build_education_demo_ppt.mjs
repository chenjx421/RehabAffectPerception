import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const OUT = "D:\\GIT\\RehabAffectPerception\\outputs\\special_education_ai_tutor_demo_presentation_robot_executor.pptx";
const PREVIEW_DIR = "D:\\GIT\\RehabAffectPerception\\outputs\\ppt_workspace_education_demo\\tmp\\preview";
const MONTAGE = "D:\\GIT\\RehabAffectPerception\\outputs\\ppt_workspace_education_demo\\tmp\\education_demo_ppt_montage.webp";
const SCREENSHOT = "D:\\GIT\\RehabAffectPerception\\outputs\\playwright\\education_demo_robot_executor.png";
const PUBLIC_URL = "https://major-moose-occur.loca.lt/education_demo";

const W = 1280;
const H = 720;
const C = {
  ink: "#111827",
  muted: "#4B5563",
  light: "#F3F4F6",
  line: "#D1D5DB",
  blue: "#2563EB",
  green: "#168348",
  amber: "#A15F10",
  red: "#C24135",
  black: "#000000",
  white: "#FFFFFF",
};

async function writeBlob(filePath, blob) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, Buffer.from(await blob.arrayBuffer()));
}

async function readImage(filePath) {
  const bytes = await fs.readFile(filePath);
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

function addText(slide, text, position, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    fontSize: options.fontSize ?? 24,
    bold: options.bold ?? false,
    color: options.color ?? C.ink,
    lineSpacing: options.lineSpacing ?? 1.14,
    alignment: options.alignment ?? "left",
    verticalAlignment: options.verticalAlignment ?? "top",
    insets: { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return shape;
}

function addBox(slide, position, options = {}) {
  return slide.shapes.add({
    geometry: "roundRect",
    position,
    fill: options.fill ?? C.white,
    line: { style: "solid", fill: options.line ?? C.line, width: options.width ?? 1 },
    borderRadius: options.borderRadius ?? 10,
  });
}

function addPill(slide, text, position, fill = C.blue) {
  const pill = addBox(slide, position, { fill, line: fill, borderRadius: 18 });
  pill.text = text;
  pill.text.style = {
    fontSize: 18,
    bold: true,
    color: C.white,
    alignment: "center",
    verticalAlignment: "middle",
    insets: { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return pill;
}

function addFooter(slide, n) {
  addText(slide, `RehabAffectPerception | demo review | ${n}`, { left: 72, top: 676, width: 360, height: 22 }, {
    fontSize: 12,
    color: "#6B7280",
  });
}

function addTitle(slide, title, subtitle, n) {
  addText(slide, title, { left: 72, top: 54, width: 820, height: 58 }, {
    fontSize: 39,
    bold: true,
    color: C.ink,
  });
  if (subtitle) {
    addText(slide, subtitle, { left: 72, top: 112, width: 900, height: 42 }, {
      fontSize: 18,
      color: C.muted,
    });
  }
  addFooter(slide, n);
}

function addBullets(slide, items, position, fontSize = 23) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = items.map((item) => `• ${item}`).join("\n");
  shape.text.style = {
    fontSize,
    color: C.ink,
    lineSpacing: 1.22,
    insets: { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return shape;
}

function addStep(slide, index, title, desc, x, y, color) {
  addPill(slide, String(index).padStart(2, "0"), { left: x, top: y, width: 56, height: 36 }, color);
  addText(slide, title, { left: x, top: y + 52, width: 200, height: 32 }, {
    fontSize: 24,
    bold: true,
  });
  addText(slide, desc, { left: x, top: y + 90, width: 220, height: 86 }, {
    fontSize: 17,
    color: C.muted,
    lineSpacing: 1.18,
  });
}

async function main() {
  await fs.mkdir(path.dirname(OUT), { recursive: true });
  await fs.mkdir(PREVIEW_DIR, { recursive: true });
  const screenshot = await readImage(SCREENSHOT);
  const deck = Presentation.create({ slideSize: { width: W, height: H } });

  // 1. Cover
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addPill(slide, "可运行 Demo", { left: 72, top: 54, width: 132, height: 38 }, C.green);
    addText(slide, "辅读学校 AI 助教 Demo", { left: 72, top: 174, width: 820, height: 76 }, {
      fontSize: 56,
      bold: true,
    });
    addText(slide, "课堂切片识别 -> 时间线融合 -> 学生状态库 -> 教师端/学生端/机器人动作输出", {
      left: 72,
      top: 268,
      width: 760,
      height: 80,
    }, {
      fontSize: 25,
      color: C.muted,
      lineSpacing: 1.16,
    });
    addBox(slide, { left: 72, top: 432, width: 780, height: 88 }, { fill: C.light, line: C.line });
    const url = addText(slide, PUBLIC_URL, { left: 98, top: 462, width: 720, height: 34 }, {
      fontSize: 24,
      bold: true,
      color: C.blue,
    });
    try {
      url.text.get(PUBLIC_URL).link = { uri: PUBLIC_URL, isExternal: true };
    } catch {}
    addText(slide, "临时公网链接：电脑保持开机、Demo 服务和隧道不断开时可访问。正式版部署到云服务器后替换为固定域名。", {
      left: 72,
      top: 540,
      width: 760,
      height: 46,
    }, {
      fontSize: 16,
      color: C.muted,
    });
    slide.images.add({
      blob: screenshot,
      contentType: "image/png",
      alt: "AI助教Demo页面截图",
      fit: "cover",
      position: { left: 890, top: 90, width: 318, height: 510 },
      geometry: "roundRect",
      borderRadius: 14,
    });
    addFooter(slide, 1);
  }

  // 2. Why this demo
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addTitle(slide, "这次 Demo 要证明什么", "不是替代老师，也不是医学诊断；先证明课堂 AI 助教闭环能跑通。", 2);
    addBullets(slide, [
      "学校真实数据尚未授权前，先用匿名模拟切片验证系统结构。",
      "重点从“识别学生怎么了”推进到“下一步应该怎么引导”。",
      "输出必须能被老师理解、能被学生端执行，也能迁移到机器人动作。",
      "语音在校园环境不稳定，因此只作为辅助证据，不单独触发高风险判断。",
    ], { left: 72, top: 210, width: 560, height: 260 }, 25);
    addBox(slide, { left: 720, top: 190, width: 408, height: 300 }, { fill: C.light, line: C.line });
    addText(slide, "核心价值", { left: 756, top: 226, width: 300, height: 42 }, {
      fontSize: 28,
      bold: true,
    });
    addText(slide, "把课堂中的分心、困惑、求助、挫败等状态转化为低刺激、可解释、可由老师接管的引导动作。", {
      left: 756,
      top: 294,
      width: 332,
      height: 126,
    }, {
      fontSize: 25,
      lineSpacing: 1.18,
      color: C.ink,
    });
  }

  // 3. Pipeline
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addTitle(slide, "系统流程：三类识别头到动作输出", "按经理提出的三段结构组织：信息处理、总结分析、信息输出。", 3);
    const y = 214;
    addStep(slide, 1, "视频头 1", "抽帧识别人脸、视线、姿态和动作，输出学生状态。", 72, y, C.blue);
    addStep(slide, 2, "视频头 2", "总结课堂场景和活动，避免脱离教学上下文。", 318, y, C.green);
    addStep(slide, 3, "语音头", "整理说话人和语音文本，同时标注噪声下的不确定性。", 564, y, C.amber);
    addStep(slide, 4, "时间线融合", "对齐人物状态、课堂事件、语音和任务表现。", 810, y, C.red);
    addBox(slide, { left: 72, top: 524, width: 1030, height: 70 }, { fill: "#EEF4FF", line: "#BFDBFE" });
    addText(slide, "最终输出：human_state + robot_action + robot_execution", {
      left: 104,
      top: 544,
      width: 960,
      height: 32,
    }, {
      fontSize: 28,
      bold: true,
      color: C.blue,
    });
  }

  // 4. Page walkthrough
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addTitle(slide, "Demo 页面怎么讲", "演示时按左、中、右三栏讲，不需要先解释模型细节。", 4);
    slide.images.add({
      blob: screenshot,
      contentType: "image/png",
      alt: "Demo页面全屏截图",
      fit: "contain",
      position: { left: 54, top: 176, width: 760, height: 426 },
      geometry: "roundRect",
      borderRadius: 10,
    });
    addBullets(slide, [
      "左：切片输入与三类识别头",
      "中：同一学生的时间线",
      "右：状态库、原因和机器人执行层",
      "顶部：切换三类课堂片段",
    ], { left: 852, top: 204, width: 350, height: 230 }, 23);
  }

  // 5. Three scenarios
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addTitle(slide, "三段内置场景覆盖什么问题", "今天不是训练真实学生模型，而是先证明产品形态和分析闭环。", 5);
    const cards = [
      ["听指令整理书包", "学生开始能跟上，但中途注意力被外界吸引。", "输出：低刺激拉回注意力"],
      ["课堂规则选择", "学生不是不配合，而是没理解题意。", "输出：拆分指令 + 教师辅助"],
      ["噪声课堂", "ASR 不稳定，不能盲信语音。", "输出：以视觉和任务行为为主"],
    ];
    cards.forEach((card, idx) => {
      const x = 72 + idx * 380;
      addBox(slide, { left: x, top: 202, width: 326, height: 306 }, { fill: C.white, line: C.line });
      addPill(slide, `场景 ${idx + 1}`, { left: x + 24, top: 226, width: 96, height: 34 }, [C.blue, C.green, C.amber][idx]);
      addText(slide, card[0], { left: x + 24, top: 286, width: 272, height: 38 }, {
        fontSize: 28,
        bold: true,
      });
      addText(slide, card[1], { left: x + 24, top: 350, width: 272, height: 72 }, {
        fontSize: 21,
        color: C.muted,
        lineSpacing: 1.16,
      });
      addText(slide, card[2], { left: x + 24, top: 452, width: 272, height: 34 }, {
        fontSize: 22,
        bold: true,
        color: [C.blue, C.green, C.amber][idx],
      });
    });
  }

  // 6. Actions
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addTitle(slide, "最终必须落到机器人可执行动作", "识别只是前半段；Demo 现在已经把动作展开到执行层。", 6);
    const rows = [
      ["学生端", "高亮当前目标、减少选项、放慢指令、暂停计时。"],
      ["教师端", "显示学生卡住的步骤、原因和建议，不公开给学生贴标签。"],
      ["机器人层", "语音、屏幕提示、表情/灯光、头部动作、教师提醒和安全约束。"],
    ];
    rows.forEach((row, idx) => {
      const y0 = 196 + idx * 124;
      addBox(slide, { left: 92, top: y0, width: 1060, height: 86 }, { fill: idx === 2 ? "#EEF4FF" : C.light, line: C.line });
      addText(slide, row[0], { left: 124, top: y0 + 24, width: 170, height: 32 }, {
        fontSize: 28,
        bold: true,
        color: idx === 2 ? C.blue : C.ink,
      });
      addText(slide, row[1], { left: 318, top: y0 + 24, width: 790, height: 38 }, {
        fontSize: 24,
        color: C.ink,
      });
    });
    addText(slide, "示例：low_attention -> regain_attention -> “我们先看这里，只做这一步” + 屏幕高亮 + 教师端提醒", {
      left: 92,
      top: 590,
      width: 1020,
      height: 34,
    }, {
      fontSize: 24,
      bold: true,
      color: C.blue,
    });
  }

  // 7. Access and next step
  {
    const slide = deck.slides.add();
    slide.background.fill = C.white;
    addTitle(slide, "演示地址与后续对接", "今天可直接打开临时公网链接；正式试点前换成固定部署。", 7);
    addBox(slide, { left: 72, top: 184, width: 1070, height: 108 }, { fill: "#EEF4FF", line: "#BFDBFE" });
    const link = addText(slide, PUBLIC_URL, { left: 106, top: 220, width: 1000, height: 40 }, {
      fontSize: 31,
      bold: true,
      color: C.blue,
    });
    try {
      link.text.get(PUBLIC_URL).link = { uri: PUBLIC_URL, isExternal: true };
    } catch {}
    addBullets(slide, [
      "临时链接适合当天会议展示；电脑关机、服务关闭或隧道断开后会失效。",
      "30 日与学校沟通时，重点确认可采集数据类型、授权边界和教师校准方式。",
      "拿到授权数据后，把模拟切片替换为真实抽帧、ASR 和教师校准标签。",
      "正式展示版建议部署到云服务器，形成稳定 HTTPS 地址和账号权限。",
    ], { left: 90, top: 350, width: 960, height: 210 }, 23);
  }

  for (const [index, slide] of deck.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    await writeBlob(path.join(PREVIEW_DIR, `${stem}.png`), await deck.export({ slide, format: "png", scale: 1 }));
    await fs.writeFile(
      path.join(PREVIEW_DIR, `${stem}.layout.json`),
      await (await slide.export({ format: "layout" })).text(),
      "utf8",
    );
  }
  await writeBlob(MONTAGE, await deck.export({ format: "webp", montage: true, scale: 1 }));
  const pptx = await PresentationFile.exportPptx(deck);
  await pptx.save(OUT);
  console.log(JSON.stringify({ out: OUT, previewDir: PREVIEW_DIR, montage: MONTAGE, publicUrl: PUBLIC_URL }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
