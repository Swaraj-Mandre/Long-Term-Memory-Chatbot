/*
  Builds the Jury 2 presentation (PS 96, Sentiment-Aware Chatbot).

  Run with:  node presentation/build_deck_jury2.js

  Same look as the Jury 1 deck (build_deck.js), so the two read as one
  project. Figures come from docs/assets/jury2, which are captured from the
  running app by docs/capture_screenshots_jury2.py and cut to size by
  presentation/crop_figures.py.
*/

const path = require("path");
const pptxgen = require("pptxgenjs");

const FIGS = path.join(__dirname, "..", "docs", "assets", "jury2");
const OUT = path.join(__dirname, "SentimentAwareChatbot_Jury2.pptx");

/* --------------------------------------------------------------- palette */
const NAVY = "1E2761";
const NAVY_SOFT = "2E3D7A";
const ICE = "CADCFC";
const CARD = "F7F9FC";
const WHITE = "FFFFFF";
const INK = "1A1D23";
const MUTED = "5B6472";
const FAINT = "8B94A3";
const LINE = "DDE3ED";
const GREEN = "047857";
const GREEN_BG = "ECFDF5";
const AMBER = "B45309";
const AMBER_BG = "FFFBEB";
const RED = "BE123C";
const RED_BG = "FFF1F2";

// One colour per emotion, the same ones the app uses.
const EMOTION_COLOURS = {
  Joy: "F59E0B", Sadness: "3B82F6", Anger: "EF4444", Fear: "8B5CF6",
  Surprise: "14B8A6", Disgust: "65A30D", Neutral: "6B7280",
};

const HEAD = "Cambria";
const BODY = "Calibri";

const W = 13.333;
const M = 0.62;
const RIGHT = W - M;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.author = "Group 03";
pres.title = "Sentiment-Aware Chatbot";

let slideNumber = 1;

/* --------------------------------------------------------------- helpers */

function contentSlide(title, kicker) {
  const s = pres.addSlide();
  s.background = { color: WHITE };
  slideNumber += 1;

  s.addText(kicker.toUpperCase(), {
    x: M, y: 0.42, w: 9, h: 0.26,
    fontFace: BODY, fontSize: 11.5, bold: true, color: FAINT,
    charSpacing: 1.4, isTextBox: true, margin: 0,
  });
  s.addText(title, {
    x: M, y: 0.7, w: W - M * 2, h: 0.68,
    fontFace: HEAD, fontSize: 32, bold: true, color: NAVY,
    isTextBox: true, margin: 0,
  });
  s.addText(String(slideNumber), {
    x: RIGHT - 0.6, y: 7.0, w: 0.6, h: 0.25,
    fontFace: BODY, fontSize: 10, color: FAINT, align: "right",
    isTextBox: true, margin: 0,
  });
  return s;
}

function card(s, x, y, w, h, fill, border) {
  s.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.1,
    fill: { color: fill || CARD },
    line: { color: border || LINE, width: 0.75 },
  });
}

function badge(s, x, y, label, fill, textColor, size) {
  const d = size || 0.42;
  s.addShape(pres.ShapeType.ellipse, {
    x, y, w: d, h: d,
    fill: { color: fill || NAVY }, line: { color: fill || NAVY, width: 0 },
  });
  s.addText(label, {
    x, y, w: d, h: d,
    fontFace: BODY, fontSize: 12.5, bold: true, color: textColor || WHITE,
    align: "center", valign: "middle", isTextBox: true, margin: 0,
  });
}

function dot(s, x, y, colour, d) {
  d = d || 0.16;
  s.addShape(pres.ShapeType.ellipse, {
    x, y, w: d, h: d, fill: { color: colour }, line: { color: colour, width: 0 },
  });
}

function text(s, value, opts) {
  s.addText(value, Object.assign({
    fontFace: BODY, fontSize: 14.5, color: INK, valign: "top",
    isTextBox: true, margin: 0,
  }, opts));
}

function bullets(s, items, opts) {
  const runs = items.map((t, i) => ({
    text: t,
    options: { bullet: { indent: 14 }, breakLine: i !== items.length - 1 },
  }));
  s.addText(runs, Object.assign({
    fontFace: BODY, fontSize: 14, color: INK, paraSpaceAfter: 8,
    valign: "top", isTextBox: true, margin: 0,
  }, opts));
}

function caption(s, value, x, y, w) {
  s.addText(value, {
    x, y, w, h: 0.32,
    fontFace: BODY, fontSize: 11, italic: true, color: FAINT,
    valign: "top", isTextBox: true, margin: 0,
  });
}

// A screenshot on a soft card, sized by width and keeping its proportions.
function figure(s, file, x, y, w, ratio) {
  const h = w / ratio;
  s.addShape(pres.ShapeType.roundRect, {
    x: x - 0.06, y: y - 0.06, w: w + 0.12, h: h + 0.12, rectRadius: 0.08,
    fill: { color: WHITE }, line: { color: LINE, width: 0.75 },
    shadow: { type: "outer", color: "1E2761", opacity: 0.12, blur: 8, offset: 2, angle: 90 },
  });
  s.addImage({ path: path.join(FIGS, file), x, y, w, h });
  return h;
}

function arrowRight(s, x, y, w) {
  s.addShape(pres.ShapeType.line, {
    x, y, w, h: 0,
    line: { color: FAINT, width: 1.5, endArrowType: "triangle" },
  });
}

function arrowDown(s, x, y, h) {
  s.addShape(pres.ShapeType.line, {
    x, y, w: 0, h,
    line: { color: FAINT, width: 1.5, endArrowType: "triangle" },
  });
}

// A box in the pipeline diagram.
function stage(s, x, y, w, h, title, sub, style) {
  const styles = {
    plain:  [CARD, LINE, NAVY, MUTED],
    dark:   [NAVY, NAVY, WHITE, ICE],
    danger: [RED_BG, "FECDD3", RED, MUTED],
  };
  const [fill, border, titleColour, subColour] = styles[style || "plain"];
  card(s, x, y, w, h, fill, border);
  text(s, title, {
    x: x + 0.1, y: y + 0.2, w: w - 0.2, h: 0.36,
    fontSize: 14.5, bold: true, color: titleColour, align: "center",
  });
  text(s, sub, {
    x: x + 0.1, y: y + 0.56, w: w - 0.2, h: h - 0.66,
    fontSize: 11.5, color: subColour, align: "center",
  });
}


/* ============================================================ 1. TITLE */
{
  const s = pres.addSlide();
  s.background = { color: NAVY };

  s.addText("Sentiment-Aware Chatbot", {
    x: M + 0.15, y: 1.75, w: 11.5, h: 1.0,
    fontFace: HEAD, fontSize: 48, bold: true, color: WHITE,
    isTextBox: true, margin: 0,
  });
  s.addText("A chatbot that notices how the user feels, adapts its tone, and responds safely to distress", {
    x: M + 0.15, y: 2.85, w: 11.0, h: 0.5,
    fontFace: BODY, fontSize: 19, color: ICE, isTextBox: true, margin: 0,
  });

  s.addShape(pres.ShapeType.roundRect, {
    x: M + 0.15, y: 3.65, w: 5.1, h: 0.5, rectRadius: 0.25,
    fill: { color: NAVY_SOFT }, line: { color: "3D4C8C", width: 0.75 },
  });
  s.addText("PS 96     |     Real-Time Scenario     |     Jury 2", {
    x: M + 0.15, y: 3.65, w: 5.1, h: 0.5,
    fontFace: BODY, fontSize: 14, color: ICE, align: "center", valign: "middle",
    isTextBox: true, margin: 0,
  });

  text(s, [
    { text: "Swaraj Mandre", options: { breakLine: true } },
    { text: "Saumya Joshi", options: { breakLine: true } },
    { text: "Siddhant Pawar" },
  ], { x: M + 0.15, y: 4.75, w: 4.5, h: 1.2, fontSize: 16, color: WHITE, paraSpaceAfter: 6 });

  text(s, "Guided by", { x: 5.6, y: 4.78, w: 5, h: 0.3, fontSize: 12, color: ICE });
  text(s, "Prof. Dr. Snehalata Funde", { x: 5.6, y: 5.05, w: 6, h: 0.35, fontSize: 16, color: WHITE });
  text(s, [
    { text: "Group 3, LY-AIA5", options: { breakLine: true } },
    { text: "MIT School of Computing", options: { breakLine: true } },
    { text: "MIT Art, Design and Technology University" },
  ], { x: 5.6, y: 5.55, w: 6.5, h: 0.9, fontSize: 12.5, color: ICE, paraSpaceAfter: 2 });

  s.addNotes(
    "Good morning. Our Jury 2 project is PS 96, a sentiment-aware chatbot. " +
    "It reads how the user feels, changes the tone of its reply, and handles distress safely. " +
    "We built it on top of our Jury 1 work, a chatbot with long-term memory, so it also remembers the user across conversations."
  );
}


/* ========================================================== 2. PROBLEM */
{
  const s = contentSlide("A chatbot reads words, not feelings", "The problem");

  text(s, "Most chatbots answer every message in the same voice. A user who is celebrating and a user who is struggling get the same style of reply.", {
    x: M, y: 1.8, w: 5.6, h: 1.0, fontSize: 16, color: INK,
  });

  const points = [
    ["1", "The wrong tone breaks trust", "A cheerful list of tips feels cold to someone who is upset."],
    ["2", "Distress needs a safe response", "A user in crisis needs real help, not a generated guess."],
    ["3", "Feelings carry over", "How a user felt last week matters today, but most bots forget it."],
  ];
  points.forEach(([n, head, sub], i) => {
    const y = 3.05 + i * 1.12;
    badge(s, M, y, n);
    text(s, head, { x: M + 0.62, y: y - 0.02, w: 5.0, h: 0.34, fontSize: 15.5, bold: true, color: NAVY });
    text(s, sub, { x: M + 0.62, y: y + 0.34, w: 5.0, h: 0.6, fontSize: 13.5, color: MUTED });
  });

  // The same message, two very different replies.
  const X = 6.95, CW = RIGHT - X;
  s.addShape(pres.ShapeType.roundRect, {
    x: RIGHT - 4.6, y: 1.8, w: 4.6, h: 0.62, rectRadius: 0.12,
    fill: { color: "2563EB" }, line: { color: "2563EB", width: 0 },
  });
  text(s, "I failed my DBMS exam again too. Nothing I do ever works.", {
    x: RIGHT - 4.5, y: 1.8, w: 4.4, h: 0.62, fontSize: 13, color: WHITE, valign: "middle",
  });

  card(s, X, 2.7, CW, 1.35, AMBER_BG, "FCD9A4");
  text(s, "A TYPICAL CHATBOT", { x: X + 0.25, y: 2.85, w: 4, h: 0.26, fontSize: 11, bold: true, color: AMBER, charSpacing: 1 });
  text(s, "Here are some tips to do better next time: make a study timetable, solve previous papers, and revise every day.", {
    x: X + 0.25, y: 3.15, w: CW - 0.5, h: 1.0, fontSize: 14, color: INK,
  });

  card(s, X, 4.3, CW, 1.75, GREEN_BG, "A7F3D0");
  text(s, "OUR CHATBOT  (REAL OUTPUT)", { x: X + 0.25, y: 4.45, w: 5, h: 0.26, fontSize: 11, bold: true, color: GREEN, charSpacing: 1 });
  text(s, "That's a heavy weight to carry. I'm sorry you're going through this. It's okay to feel crushed. You don't have to figure it all out alone. Is there someone you trust you can talk to?", {
    x: X + 0.25, y: 4.75, w: CW - 0.5, h: 1.2, fontSize: 14, color: INK,
  });
  caption(s, "Same message, same facts. Only the reading of emotion is different.", X, 6.2, CW);

  s.addNotes(
    "The problem is simple. A normal chatbot gives the same kind of reply whatever the user feels. " +
    "On the right is the same message answered two ways. The top one is technically correct but feels cold. " +
    "The bottom one is the actual output of our system. It notices the user is low and responds gently."
  );
}


/* ===================================================== 3. PS 96 MAPPED */
{
  const s = contentSlide("Every step of PS 96, and where it lives", "Problem statement");

  const rows = [
    ["Frame a bot that adapts tone to emotion", "Our Jury 1 memory chatbot now reads emotion before every reply"],
    ["Detect user sentiment per message", "A local emotion model and the LLM read each message, then combine"],
    ["Adjust the reply tone accordingly", "Seven tone rules, one per emotion, placed in the system prompt"],
    ["Test on varied emotional inputs", "42 labelled messages, 10 crisis messages, 8 look-alike phrases"],
    ["Add escalation for distress", "Three safety levels. A crisis is handled by fixed rules, not the LLM"],
    ["Present the bot", "Live demo with a panel that explains why each reply was written"],
  ];

  text(s, "PS 96 STEP", { x: M + 0.62, y: 1.72, w: 4, h: 0.26, fontSize: 11, bold: true, color: FAINT, charSpacing: 1 });
  text(s, "WHAT WE BUILT", { x: 5.75, y: 1.72, w: 4, h: 0.26, fontSize: 11, bold: true, color: FAINT, charSpacing: 1 });

  rows.forEach(([step, built], i) => {
    const y = 2.08 + i * 0.78;
    card(s, M, y, RIGHT - M, 0.64, i % 2 === 0 ? CARD : WHITE);
    badge(s, M + 0.14, y + 0.12, String(i + 1), NAVY, WHITE, 0.4);
    text(s, step, { x: M + 0.72, y, w: 4.3, h: 0.64, fontSize: 14.5, bold: true, color: NAVY, valign: "middle" });
    text(s, built, { x: 5.75, y, w: 6.8, h: 0.64, fontSize: 14, color: INK, valign: "middle" });
  });

  s.addNotes(
    "This slide maps the six steps of PS 96 to what we built, so the panel can see that every step is covered. " +
    "We will go through steps two, three and five in detail, then show the test results for step four."
  );
}


/* ===================================================== 4. JURY 1 + 2 */
{
  const s = contentSlide("Built on our Jury 1 memory chatbot", "Starting point");

  const columns = [
    {
      x: M, head: "KEPT FROM JURY 1", colour: MUTED, fill: CARD, border: LINE,
      items: [
        ["Long-term memory", "Facts about the user stay on disk between sessions"],
        ["Search by meaning", "Local embeddings find the memories that matter"],
        ["Newer facts replace older ones", "Moving from Pune to Mumbai retires Pune"],
        ["Privacy filter", "Emails and phone numbers are removed before saving"],
      ],
    },
    {
      x: 7.0, head: "ADDED FOR JURY 2", colour: NAVY, fill: "EEF2FB", border: ICE,
      items: [
        ["Emotion detection", "Two readers decide how the user feels"],
        ["Tone adaptation", "The emotion decides how the reply is written"],
        ["Distress escalation", "Three levels, with a fixed reply for a crisis"],
        ["Mood memory", "How the user felt is remembered across sessions"],
      ],
    },
  ];

  columns.forEach((col) => {
    const cw = 5.71;
    card(s, col.x, 1.8, cw, 4.75, col.fill, col.border);
    text(s, col.head, { x: col.x + 0.35, y: 2.05, w: 5, h: 0.28, fontSize: 12, bold: true, color: col.colour, charSpacing: 1.2 });
    col.items.forEach(([head, sub], i) => {
      const y = 2.6 + i * 0.95;
      dot(s, col.x + 0.38, y + 0.1, col.colour, 0.15);
      text(s, head, { x: col.x + 0.7, y, w: cw - 1.0, h: 0.34, fontSize: 15.5, bold: true, color: NAVY });
      text(s, sub, { x: col.x + 0.7, y: y + 0.34, w: cw - 1.0, h: 0.5, fontSize: 13.5, color: MUTED });
    });
  });

  s.addShape(pres.ShapeType.rightArrow, {
    x: 6.43, y: 3.95, w: 0.48, h: 0.45, fill: { color: NAVY }, line: { color: NAVY, width: 0 },
  });

  s.addNotes(
    "We did not start from zero. On the left is what we kept from Jury 1: long-term memory, search by meaning, fact replacement and the privacy filter. " +
    "On the right is what is new for Jury 2. The memory is what makes our version different: the bot also remembers how the user felt."
  );
}


/* ===================================================== 5. ARCHITECTURE */
{
  const s = contentSlide("How one message travels through the system", "Architecture");

  const bw = 2.08, gap = 0.42, bh = 1.1;
  const x1 = M, x2 = M + bw + gap, x3 = x2 + bw + gap;
  const row1 = 1.85, row2 = 3.65;

  stage(s, x1, row1, bw, bh, "User message", "Typed in the browser");
  arrowRight(s, x1 + bw + 0.04, row1 + bh / 2, gap - 0.08);
  stage(s, x2, row1, bw, bh, "Crisis check", "Fixed rules, no network", "dark");
  arrowRight(s, x2 + bw + 0.04, row1 + bh / 2, gap + 0.5);
  text(s, "crisis", { x: x2 + bw + 0.05, y: row1 + bh / 2 - 0.32, w: 0.9, h: 0.25, fontSize: 11, color: RED, align: "center" });
  stage(s, x3 + 0.5, row1, 2.7, bh, "Fixed safe reply", "Helplines shown, LLM skipped", "danger");

  arrowDown(s, x2 + bw / 2, row1 + bh + 0.04, row2 - row1 - bh - 0.08);
  text(s, "no crisis", { x: x2 + bw / 2 + 0.1, y: row1 + bh + 0.18, w: 1.2, h: 0.25, fontSize: 11, color: MUTED });

  const flow = [
    ["Read emotion", "Local model and LLM, combined"],
    ["Safety and tone", "Pick the level and the tone"],
    ["Search memory", "ChromaDB, by meaning"],
    ["Write the reply", "DeepSeek v4 Flash, streamed"],
  ];
  flow.forEach(([head, sub], i) => {
    const x = x2 + i * (bw + gap);
    stage(s, x, row2, bw, bh, head, sub, i === 0 ? "dark" : "plain");
    if (i < flow.length - 1) arrowRight(s, x + bw + 0.04, row2 + bh / 2, gap - 0.08);
  });

  const notes = [
    ["One call, two jobs", "The same LLM call reads the facts and the emotion, so emotion adds no extra wait."],
    ["Safety comes first", "The crisis check runs before any model, so it works even without internet."],
    ["Explained live", "Emotion, tone and memory appear on screen before the reply is written."],
  ];
  notes.forEach(([head, sub], i) => {
    const x = M + i * 4.1;
    text(s, head, { x, y: 5.3, w: 3.8, h: 0.32, fontSize: 15, bold: true, color: NAVY });
    text(s, sub, { x, y: 5.64, w: 3.8, h: 0.8, fontSize: 13.5, color: MUTED });
  });

  s.addNotes(
    "Every message follows this path. First, a crisis check using fixed rules. If it finds crisis wording, the bot skips the LLM and shows a fixed safe reply. " +
    "Otherwise, two readers detect the emotion, we pick a safety level and a tone, search memory, and the LLM writes the reply in that tone. " +
    "Emotion detection adds no delay, because the same LLM call that extracts facts also reads the emotion."
  );
}


/* ================================================ 6. DETECTING EMOTION */
{
  const s = contentSlide("Two readers, one decision", "Step 2, detecting emotion");

  const readers = [
    ["Local emotion model", "DistilRoBERTa, 7 emotions", "Runs on this machine, free and repeatable", "Reads words, so sarcasm can fool it"],
    ["Large language model", "DeepSeek v4 Flash", "Reads the situation, catches sarcasm", "Needs the network, can be slow"],
  ];
  readers.forEach(([head, model, good, weak], i) => {
    const x = M + i * 3.35, cw = 3.15;
    card(s, x, 1.8, cw, 2.05);
    text(s, head, { x: x + 0.22, y: 1.95, w: cw - 0.4, h: 0.34, fontSize: 15.5, bold: true, color: NAVY });
    text(s, model, { x: x + 0.22, y: 2.3, w: cw - 0.4, h: 0.3, fontSize: 12.5, color: MUTED });
    text(s, [
      { text: "+  " + good, options: { color: GREEN, breakLine: true } },
      { text: "-  " + weak, options: { color: AMBER } },
    ], { x: x + 0.22, y: 2.75, w: cw - 0.4, h: 1.0, fontSize: 13, paraSpaceAfter: 6 });
  });

  text(s, "HOW THEY ARE COMBINED", { x: M, y: 4.12, w: 5, h: 0.26, fontSize: 11, bold: true, color: FAINT, charSpacing: 1 });
  const rules = [
    ["Both agree", "Use it, with high confidence", GREEN],
    ["They disagree", "Use the LLM, as it reads context, and show the disagreement", AMBER],
    ["LLM unavailable", "Use the local model alone, or neutral if it is unsure", MUTED],
  ];
  rules.forEach(([when, then, colour], i) => {
    const y = 4.48 + i * 0.66;
    dot(s, M + 0.02, y + 0.12, colour, 0.15);
    text(s, when, { x: M + 0.32, y, w: 1.8, h: 0.4, fontSize: 14, bold: true, color: INK });
    text(s, then, { x: M + 2.15, y, w: 4.5, h: 0.6, fontSize: 13.5, color: MUTED });
  });

  const fx = 7.75, fw = RIGHT - fx;
  const fh = figure(s, "fig_emotion_disagree.png", fx, 1.85, fw, 720 / 487);
  caption(s, "Real case: \"Great, another rejection email.\" The local model sees the word great. The LLM reads the feeling behind it.",
    fx, 1.85 + fh + 0.2, fw);

  s.addNotes(
    "This answers the first jury question. We do not trust a single reader. A local emotion model scores every message against seven emotions. " +
    "The LLM reads the same message with context. When they agree we are confident. When they disagree, we use the LLM and the screen shows the disagreement. " +
    "The screenshot is a real sarcastic message. The local model said joy because of the word great. The LLM read the real feeling behind it, frustration, so the bot replied calmly instead of cheerfully."
  );
}


/* =================================================== 7. ADAPTING TONE */
{
  const s = contentSlide("The emotion decides how the reply is written", "Step 3, adapting tone");

  const tones = [
    ["Joy", "Cheerful", "Match their energy, share the good news"],
    ["Sadness", "Gentle", "Acknowledge first, short kind sentences"],
    ["Anger", "Calm", "Do not argue, then help with the problem"],
    ["Fear", "Reassuring", "Steady voice, one small next step"],
    ["Surprise", "Curious", "Help them make sense of it"],
    ["Disgust", "Understanding", "Acknowledge without judging"],
    ["Neutral", "Friendly", "Clear and to the point"],
  ];

  text(s, "EMOTION", { x: M + 0.35, y: 1.75, w: 1.5, h: 0.26, fontSize: 11, bold: true, color: FAINT, charSpacing: 1 });
  text(s, "TONE", { x: 2.35, y: 1.75, w: 1.5, h: 0.26, fontSize: 11, bold: true, color: FAINT, charSpacing: 1 });
  text(s, "INSTRUCTION GIVEN TO THE LLM", { x: 3.95, y: 1.75, w: 3.5, h: 0.26, fontSize: 11, bold: true, color: FAINT, charSpacing: 1 });

  tones.forEach(([emotion, tone, rule], i) => {
    const y = 2.1 + i * 0.56;
    if (i % 2 === 0) card(s, M, y, 6.55, 0.5, CARD, CARD);
    dot(s, M + 0.12, y + 0.17, EMOTION_COLOURS[emotion], 0.16);
    text(s, emotion, { x: M + 0.35, y, w: 1.4, h: 0.5, fontSize: 14, color: INK, valign: "middle" });
    text(s, tone, { x: 2.35, y, w: 1.55, h: 0.5, fontSize: 14, bold: true, color: NAVY, valign: "middle" });
    text(s, rule, { x: 3.95, y, w: 3.2, h: 0.5, fontSize: 12.5, color: MUTED, valign: "middle" });
  });

  text(s, "The instruction is added to the system prompt, so the LLM writes the reply in that tone from the start.", {
    x: M, y: 6.15, w: 6.5, h: 0.6, fontSize: 13.5, color: INK,
  });

  const fx = 7.55, fw = RIGHT - fx;
  const fh = figure(s, "chat_tones.png", fx, 1.85, fw, 1800 / 1280);
  caption(s, "Three messages, three tones. The tag under each reply shows the tone used.", fx, 1.85 + fh + 0.2, fw);

  s.addNotes(
    "Once we know the emotion, a simple lookup table picks the tone. Each tone is one instruction, which we add to the system prompt. " +
    "On the right are three real replies from one conversation: cheerful for good news, calm for a frustrating rejection, and gentle with a check-in when the user kept feeling low."
  );
}


/* ================================================ 8. DISTRESS LEVELS */
{
  const s = contentSlide("Three levels of care", "Step 5, escalation for distress");

  const levels = [
    ["0", "Normal", GREEN, GREEN_BG, "A7F3D0",
      "Any emotion, no sign of distress",
      "Adapts the tone. Nothing else changes."],
    ["1", "Concern", AMBER, AMBER_BG, "FCD9A4",
      "Three negative messages in a row, or the LLM sees the user is struggling",
      "Gentle check-in. Mentions that help is available, such as Tele-MANAS 14416."],
    ["2", "Crisis", RED, RED_BG, "FECDD3",
      "Words about self-harm or not wanting to live",
      "Skips the LLM. Shows a fixed reply with helplines. The message is not stored."],
  ];

  const cw = 3.85, gap = 0.27;
  levels.forEach(([n, name, colour, fill, border, when, does], i) => {
    const x = M + i * (cw + gap);
    card(s, x, 1.8, cw, 3.35, fill, border);
    badge(s, x + 0.28, 2.05, n, colour);
    text(s, name, { x: x + 0.85, y: 2.08, w: 2.6, h: 0.38, fontSize: 19, bold: true, color: colour });
    text(s, "WHEN", { x: x + 0.3, y: 2.75, w: 2, h: 0.24, fontSize: 10.5, bold: true, color: FAINT, charSpacing: 1 });
    text(s, when, { x: x + 0.3, y: 3.0, w: cw - 0.55, h: 0.8, fontSize: 13.5, color: INK });
    text(s, "WHAT THE BOT DOES", { x: x + 0.3, y: 3.85, w: 3, h: 0.24, fontSize: 10.5, bold: true, color: FAINT, charSpacing: 1 });
    text(s, does, { x: x + 0.3, y: 4.1, w: cw - 0.55, h: 0.95, fontSize: 13.5, color: INK });
  });

  card(s, M, 5.45, RIGHT - M, 1.15, NAVY, NAVY);
  text(s, "Why a crisis uses fixed rules, not the LLM", {
    x: M + 0.35, y: 5.6, w: 11, h: 0.34, fontSize: 15.5, bold: true, color: WHITE,
  });
  text(s, "A model can misread a message, run out of tokens or lose its connection. A reply to someone in crisis cannot depend on any of that, so it is written once, checked, and always shown the same way.", {
    x: M + 0.35, y: 5.95, w: RIGHT - M - 0.7, h: 0.6, fontSize: 13.5, color: ICE,
  });

  s.addNotes(
    "This answers the second jury question. There are three levels. Normal only changes the tone. Concern adds a gentle check-in. " +
    "Crisis is different: fixed rules catch self-harm wording, the LLM is skipped completely, and a reviewed reply with helpline numbers is shown. " +
    "We do this because a crisis reply must never depend on a model behaving well or a network being up."
  );
}


/* =================================================== 9. CRISIS IN APP */
{
  const s = contentSlide("What the user sees in a crisis", "Step 5, in the app");

  const lw = 7.55;
  const lh = figure(s, "chat_crisis.png", M, 1.85, lw, 1800 / 792);

  const points = [
    ["Helplines first", "Large numbers that can be read at a glance"],
    ["Calm, not alarming", "Soft colours and kind words"],
    ["Honest about its source", "Marked as a fixed reply, not AI generated"],
  ];
  points.forEach(([head, sub], i) => {
    const x = M + i * 2.6;
    const y = 1.85 + lh + 0.4;
    text(s, head, { x, y, w: 2.45, h: 0.32, fontSize: 14.5, bold: true, color: NAVY });
    text(s, sub, { x, y: y + 0.34, w: 2.4, h: 0.6, fontSize: 13, color: MUTED });
  });

  const fx = 9.0, fw = RIGHT - fx;
  const fh = figure(s, "fig_crisis_panel.png", fx, 1.85, fw, 720 / 887);
  caption(s, "The LLM was skipped. The matched phrase is shown.", fx, 1.85 + fh + 0.16, fw);

  s.addNotes(
    "Here is the crisis reply in the app. The helpline numbers are the largest thing on the card. " +
    "On the right, the panel shows exactly what happened: the crisis rule matched, the LLM was skipped, and a fixed reply was used."
  );
}


/* ===================================================== 10. MOOD MEMORY */
{
  const s = contentSlide("It remembers how you felt, not only what you said", "Long-term memory of emotion");

  const lw = 7.55;
  const lh = figure(s, "chat_follow_up.png", M, 1.85, lw, 1800 / 548);
  caption(s, "A new session clears recent messages. The bot still recalls the internship from long-term memory.", M, 1.85 + lh + 0.18, lw);

  const ty = 1.85 + lh + 0.85;
  const th = figure(s, "fig_timeline.png", M, ty, 5.2, 730 / 110);
  caption(s, "Each dot is one message. S1 and S2 are separate sessions. The ring marks a crisis.", M, ty + th + 0.2, lw);

  const X = 8.75, cw = RIGHT - X;
  card(s, X, 1.8, cw, 4.5, "EEF2FB", ICE);
  text(s, "What is stored", { x: X + 0.3, y: 2.0, w: cw - 0.6, h: 0.36, fontSize: 16, bold: true, color: NAVY });
  bullets(s, [
    "The emotion and its confidence",
    "A short reason, such as worried about exam results",
    "Never the message itself",
    "For a crisis, only the note: distress flagged",
  ], { x: X + 0.3, y: 2.45, w: cw - 0.6, h: 2.2, fontSize: 13.5 });
  text(s, "Why it matters", { x: X + 0.3, y: 4.45, w: cw - 0.6, h: 0.36, fontSize: 16, bold: true, color: NAVY });
  text(s, "In the next session the bot can ask how the exam went, instead of starting cold.", {
    x: X + 0.3, y: 4.85, w: cw - 0.6, h: 1.1, fontSize: 13.5, color: INK,
  });

  s.addNotes(
    "This is where Jury 1 and Jury 2 meet. A normal sentiment bot only knows how you feel in this one message. " +
    "Ours keeps a short mood history across sessions. It stores the emotion and a short reason, never the message itself, and for a crisis only a neutral note."
  );
}


/* ===================================================== 11. EVALUATION */
{
  const s = contentSlide("Results", "Step 4, testing");

  const tiles = [
    ["97.6%", "Emotion accuracy", NAVY],
    ["7 / 7", "Sarcastic or mixed messages", NAVY],
    ["10 / 10", "Crisis messages caught", GREEN],
    ["0 / 8", "False alarms", GREEN],
  ];
  tiles.forEach(([value, label, colour], i) => {
    const x = M + (i % 2) * 3.05, y = 1.85 + Math.floor(i / 2) * 1.6;
    card(s, x, y, 2.85, 1.4);
    text(s, value, { x, y: y + 0.18, w: 2.85, h: 0.65, fontFace: HEAD, fontSize: 32, bold: true, color: colour, align: "center" });
    text(s, label.toUpperCase(), { x: x + 0.1, y: y + 0.88, w: 2.65, h: 0.4, fontSize: 10.5, color: MUTED, align: "center", charSpacing: 0.6 });
  });

  text(s, "42 messages, 6 for each of the 7 emotions. The correct label for each was written before any test was run. 7 of them are hard: sarcasm and mixed feelings. False alarms were tested on everyday phrases such as \"this traffic is killing me\".", {
    x: M, y: 5.2, w: 5.95, h: 1.4, fontSize: 13, color: MUTED,
  });

  s.addChart(pres.ChartType.bar, [
    { name: "All 42 messages", labels: ["Local model alone", "LLM alone", "Combined (used by bot)"], values: [83.3, 97.6, 97.6] },
    { name: "7 hard messages", labels: ["Local model alone", "LLM alone", "Combined (used by bot)"], values: [28.6, 100, 100] },
  ], {
    x: 7.05, y: 1.75, w: RIGHT - 7.05, h: 4.85,
    barDir: "col", barGrouping: "clustered", barGapWidthPct: 60,
    chartColors: [NAVY, "8FA6E0"],
    showTitle: true, title: "Accuracy (%) by reader", titleFontFace: BODY, titleFontSize: 14, titleColor: INK,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 11, dataLabelColor: INK, dataLabelFontFace: BODY,
    dataLabelFormatCode: "0.0",
    valAxisMinVal: 0, valAxisMaxVal: 110, valAxisHidden: true,
    valGridLine: { style: "none" }, catGridLine: { style: "none" },
    catAxisLabelColor: MUTED, catAxisLabelFontSize: 12, catAxisLabelFontFace: BODY,
    showLegend: true, legendPos: "b", legendFontSize: 12, legendFontFace: BODY, legendColor: MUTED,
  });

  s.addNotes(
    "We tested on 42 labelled messages, with the answers written down before testing. The combined system scores 97.6 percent. " +
    "The local model alone scores 83.3 percent, and gets only 2 of the 7 hard messages right. With the LLM, all 7 are correct. " +
    "The safety rules caught all 10 crisis messages and raised no false alarm on 8 everyday phrases."
  );
}


/* ============================================== 12. JURY QUESTIONS */
{
  const s = contentSlide("Answers to the two key questions", "Questions from PS 96");

  const qs = [
    ["Q1", "How do you detect sentiment reliably?", [
      "Two independent readers: a local emotion model and the LLM",
      "When they disagree, the LLM decides and the screen shows it",
      "Measured: 97.6% on 42 labelled messages, and all 7 hard cases correct",
    ]],
    ["Q2", "How do you handle a distressed user safely?", [
      "Fixed rules check every message before any model runs",
      "A crisis gets a reviewed reply with helplines, never a generated one",
      "Measured: 10 of 10 crisis messages caught, 0 of 8 false alarms",
    ]],
  ];

  qs.forEach(([tag, question, answers], i) => {
    const x = M + i * 6.15, cw = 5.9;
    card(s, x, 1.8, cw, 4.3);
    badge(s, x + 0.3, 2.05, tag, NAVY, WHITE, 0.55);
    text(s, question, { x: x + 1.05, y: 2.05, w: cw - 1.35, h: 0.8, fontFace: HEAD, fontSize: 19, bold: true, color: NAVY, valign: "middle" });
    answers.forEach((a, j) => {
      const y = 3.15 + j * 0.9;
      dot(s, x + 0.38, y + 0.1, j === 2 ? GREEN : NAVY, 0.14);
      text(s, a, { x: x + 0.7, y, w: cw - 1.0, h: 0.85, fontSize: 15, color: j === 2 ? GREEN : INK, bold: j === 2 });
    });
  });

  s.addNotes(
    "PS 96 lists two likely questions, so here are our answers in one place. " +
    "Reliability comes from two readers and an honest rule for disagreement, backed by measured results. " +
    "Safety comes from fixed rules that run first and a reply that is never generated."
  );
}


/* ==================================================== 13. LIMITATIONS */
{
  const s = contentSlide("Limitations and next steps", "Being honest");

  const cols = [
    ["WHAT IT DOES NOT DO WELL", AMBER, AMBER_BG, "FCD9A4", [
      "The local emotion model understands English only",
      "Fixed rules can miss indirect wording. The LLM is a second check, but it can miss too",
      "Combining does not beat the LLM on accuracy. It adds a fallback and a signal for tricky messages",
      "It is a support tool, not a counsellor. It points people to real help",
    ]],
    ["WHAT WE WOULD ADD NEXT", GREEN, GREEN_BG, "A7F3D0", [
      "A multilingual emotion model for Hindi and Marathi",
      "A larger test set written by people outside the team",
      "Alert a trusted contact in a crisis, only with the user's consent",
      "Crisis wording reviewed by a mental health professional",
    ]],
  ];

  cols.forEach(([head, colour, fill, border, items], i) => {
    const x = M + i * 6.15, cw = 5.9;
    card(s, x, 1.8, cw, 4.3, fill, border);
    text(s, head, { x: x + 0.35, y: 2.05, w: cw - 0.6, h: 0.28, fontSize: 12, bold: true, color: colour, charSpacing: 1.2 });
    items.forEach((item, j) => {
      const y = 2.6 + j * 0.88;
      dot(s, x + 0.38, y + 0.1, colour, 0.14);
      text(s, item, { x: x + 0.7, y, w: cw - 1.0, h: 0.85, fontSize: 14.5, color: INK });
    });
  });

  s.addNotes(
    "We want to be clear about the limits. The local model is English only, rules can miss indirect wording, and combining the readers does not raise accuracy above the LLM. " +
    "Its value is a working fallback when the LLM is down. Next, we would add Indian language support, a larger independent test set, and professional review of the crisis wording."
  );
}


/* ==================================================== 14. TECH STACK */
{
  const s = contentSlide("Tech stack", "Tools and models");

  const parts = [
    ["Language model", "DeepSeek v4 Flash", "Reads facts and emotion, writes the reply"],
    ["Emotion model", "DistilRoBERTa", "7 emotions, runs on this machine"],
    ["Embeddings", "all-MiniLM-L6-v2", "Searches memory by meaning, runs locally"],
    ["Vector database", "ChromaDB", "Keeps long-term memory on disk"],
    ["Safety", "Fixed rules", "Crisis check before any model runs"],
    ["Mood memory", "JSON file", "Emotion history across sessions"],
    ["Interface", "HTML, CSS, JavaScript", "Python server, reply streamed live"],
    ["Evaluation", "Python scripts", "Accuracy, macro F1, safety checks"],
  ];

  const cw = 2.86, ch = 2.15, gx = 0.21, gy = 0.3;
  parts.forEach(([part, value, purpose], i) => {
    const x = M + (i % 4) * (cw + gx), y = 1.85 + Math.floor(i / 4) * (ch + gy);
    card(s, x, y, cw, ch);
    text(s, part.toUpperCase(), { x: x + 0.25, y: y + 0.25, w: cw - 0.5, h: 0.26, fontSize: 10.5, bold: true, color: FAINT, charSpacing: 1 });
    text(s, value, { x: x + 0.25, y: y + 0.6, w: cw - 0.5, h: 0.45, fontSize: 16.5, bold: true, color: NAVY });
    text(s, purpose, { x: x + 0.25, y: y + 1.15, w: cw - 0.5, h: 0.85, fontSize: 13, color: MUTED });
  });

  s.addNotes(
    "Our stack in one view. Two models run on our own machine, the emotion model and the embedding model, so stored memories never leave it. " +
    "The LLM is DeepSeek v4 Flash, served through AtlasCloud."
  );
}


/* ===================================================== 15. CLOSING */
{
  const s = pres.addSlide();
  s.background = { color: NAVY };

  s.addText("Thank you", {
    x: M + 0.15, y: 2.2, w: 11, h: 1.0,
    fontFace: HEAD, fontSize: 48, bold: true, color: WHITE, isTextBox: true, margin: 0,
  });
  s.addText("We are happy to take questions, and to run the live demo.", {
    x: M + 0.15, y: 3.3, w: 11, h: 0.5,
    fontFace: BODY, fontSize: 19, color: ICE, isTextBox: true, margin: 0,
  });

  s.addShape(pres.ShapeType.roundRect, {
    x: M + 0.15, y: 4.3, w: 7.6, h: 0.55, rectRadius: 0.27,
    fill: { color: NAVY_SOFT }, line: { color: "3D4C8C", width: 0.75 },
  });
  s.addText("github.com/Swaraj-Mandre/Long-Term-Memory-Chatbot", {
    x: M + 0.15, y: 4.3, w: 7.6, h: 0.55,
    fontFace: BODY, fontSize: 15, color: WHITE, align: "center", valign: "middle",
    isTextBox: true, margin: 0,
  });

  s.addText("Swaraj Mandre   |   Saumya Joshi   |   Siddhant Pawar", {
    x: M + 0.15, y: 5.5, w: 11, h: 0.35,
    fontFace: BODY, fontSize: 14, color: ICE, isTextBox: true, margin: 0,
  });

  s.addNotes("Thank you. We can show the live demo now, or take questions first.");
}


pres.writeFile({ fileName: OUT }).then(() => console.log("Written", OUT));
