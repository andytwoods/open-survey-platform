const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const { applyTheme } = require("/Users/andytwoods/.claude/skills/synced/1e7ed55c-a04e-4724-b089-680c66259a96_e1d9f8cf-0cc6-4615-a4bd-03087fa084ed/pptx/scripts/apply_theme.js");

// Purple: the colours of the 8-bit project icon (indigo, violet, cyan, phosphor green).
const THEME = {
  name: "HubAI pitch",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1D1652", // deep indigo (text on light, dark background)
    lt1: "FFFFFF",
    dk2: "3A2F9E", // violet
    lt2: "F1EDFB", // pale lilac
    accent1: "6A4FD2", // violet accent
    accent2: "19E6FF", // cyan
    accent3: "6DFF7A", // phosphor green
    accent4: "D5C9F4",
    accent5: "A48FE6",
    accent6: "FFB547",
    hlink: "19E6FF",
    folHlink: "A48FE6",
  },
};

async function icon(Comp, color, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size: String(size) }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
  pres.title = "HubAI: one board for a team's AI agents";
  pres.author = "Andy Woods";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const C = pres.SchemeColor;

  pres.defineSlideMaster({
    title: "DARK_TITLE_ONLY",
    background: { color: C.text1 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.45, w: 12.1, h: 1.0, fontSize: 40, bold: true, color: C.background1, valign: "middle" }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "LIGHT_TITLE_ONLY",
    background: { color: C.background1 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.45, w: 12.1, h: 1.0, fontSize: 40, bold: true, color: C.text1, valign: "middle" }, text: "" } },
    ],
  });

  const robot = await icon(fa.FaRobot, "19E6FF");
  const robotDim = await icon(fa.FaRobot, "A48FE6");
  const columns = await icon(fa.FaColumns, "6A4FD2");
  const envelope = await icon(fa.FaEnvelope, "6A4FD2");
  const cloud = await icon(fa.FaCloud, "6A4FD2");
  const hand = await icon(fa.FaHandPaper, "1D1652");
  const inbox = await icon(fa.FaInbox, "1D1652");
  const desktop = await icon(fa.FaDesktop, "1D1652");
  const redo = await icon(fa.FaRedo, "1D1652");
  const plug = await icon(fa.FaPlug, "1D1652");
  const userIcon = await icon(fa.FaUserGraduate, "A48FE6");

  // ---------------------------------------------------------------- 1. The problem
  pres.addSection({ title: "Problem" });
  let s = pres.addSlide({ masterName: "DARK_TITLE_ONLY", sectionTitle: "Problem" });
  s.addText("Many AI agents. No shared view.", { placeholder: "title" });
  s.addText(
    [
      { text: "Scientists now build research software with AI agents", options: { bullet: true, breakLine: true } },
      { text: "One person can run many agents; a lab runs more", options: { bullet: true, breakLine: true } },
      { text: "They can't see each other, so work collides", options: { bullet: true } },
    ],
    { x: 0.6, y: 1.8, w: 6.2, h: 2.6, fontSize: 22, color: C.background1, paraSpaceAfter: 14, valign: "top", isTextBox: true, objectName: "problem-points" }
  );
  // Three agents, each in its own bubble, with a clash between them.
  const agents = [
    { x: 7.6, y: 1.9, label: "Your agent" },
    { x: 10.3, y: 1.9, label: "Colleague's agent" },
    { x: 8.95, y: 4.2, label: "Student's agent" },
  ];
  agents.forEach((a, i) => {
    s.addShape(pres.shapes.OVAL, { x: a.x, y: a.y, w: 2.0, h: 2.0, fill: { color: C.text2 }, line: { color: C.accent2, width: 1.5 }, objectName: `agent-${i}` });
    s.addImage({ data: robot, x: a.x + 0.65, y: a.y + 0.35, w: 0.7, h: 0.7, objectName: `agent-icon-${i}` });
    s.addText(a.label, { x: a.x, y: a.y + 1.15, w: 2.0, h: 0.5, fontSize: 13, color: C.background1, align: "center", isTextBox: true, margin: 0, objectName: `agent-label-${i}` });
  });
  s.addText("?", { x: 9.55, y: 2.3, w: 0.8, h: 1.0, fontSize: 48, bold: true, color: C.accent6, align: "center", isTextBox: true, objectName: "clash-1" });
  s.addText("?", { x: 8.55, y: 3.65, w: 0.6, h: 0.7, fontSize: 36, bold: true, color: C.accent6, align: "center", isTextBox: true, objectName: "clash-2" });
  s.addText("?", { x: 10.85, y: 3.65, w: 0.6, h: 0.7, fontSize: 36, bold: true, color: C.accent6, align: "center", isTextBox: true, objectName: "clash-3" });
  s.addText("HubAI: first commit Saturday 10:37; built during the hackathon", { x: 0.6, y: 6.8, w: 8, h: 0.4, fontSize: 11, color: C.accent5, italic: true, isTextBox: true, margin: 0, objectName: "footer-note" });
  s.addNotes(
    "About 25 seconds.\n" +
      "Scientists increasingly build their own research software, and more and more of it is written by AI coding agents.\n" +
      "One person can run several agents at once; a lab or a hackathon team runs many more, on many machines.\n" +
      "The problem: those agents can't see each other. Two build the same thing, one breaks another's work, and nobody notices until it's merged."
  );

  // ---------------------------------------------------------------- 2. The old way
  pres.addSection({ title: "Old way" });
  s = pres.addSlide({ masterName: "LIGHT_TITLE_ONLY", sectionTitle: "Old way" });
  s.addText("Today's tools stop at one person", { placeholder: "title" });
  const cards = [
    { img: columns, head: "Kanban apps for agents", names: "Vibe Kanban, Kanbots, Kanban Code", gap: "One person, one machine" },
    { img: envelope, head: "Agent messaging", names: "MCP Agent Mail", gap: "Messages, but no shared board" },
    { img: cloud, head: "Vendor cloud agents", names: "GitHub Copilot coding agent", gap: "Paid, and runs on their machines" },
  ];
  cards.forEach((c, i) => {
    const x = 0.6 + i * 4.1;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.75, w: 3.8, h: 3.55, rectRadius: 0.15, fill: { color: C.background2 }, line: { color: C.background2 }, objectName: `card-${i}` });
    s.addShape(pres.shapes.OVAL, { x: x + 0.35, y: 2.05, w: 0.9, h: 0.9, fill: { color: C.background1 }, line: { color: C.background1 }, objectName: `card-icon-bg-${i}` });
    s.addImage({ data: c.img, x: x + 0.55, y: 2.25, w: 0.5, h: 0.5, objectName: `card-icon-${i}` });
    s.addText(c.head, { x: x + 0.35, y: 3.1, w: 3.2, h: 0.5, fontSize: 20, bold: true, color: C.text1, isTextBox: true, margin: 0, objectName: `card-head-${i}` });
    s.addText(c.names, { x: x + 0.35, y: 3.6, w: 3.2, h: 0.7, fontSize: 14, color: C.text2, isTextBox: true, margin: 0, valign: "top", objectName: `card-names-${i}` });
    s.addText(c.gap, { x: x + 0.35, y: 4.4, w: 3.2, h: 0.7, fontSize: 15, italic: true, color: C.accent1, isTextBox: true, margin: 0, valign: "top", objectName: `card-gap-${i}` });
  });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 5.65, w: 12.1, h: 1.1, rectRadius: 0.15, fill: { color: C.text1 }, line: { color: C.text1 }, objectName: "gap-box" });
  s.addText(
    [
      { text: "Missing: ", options: { bold: true, color: C.accent2 } },
      { text: "one board for a team's people, their agents and their spare PCs", options: { color: C.background1 } },
    ],
    { x: 0.9, y: 5.65, w: 11.5, h: 1.1, fontSize: 22, valign: "middle", isTextBox: true, margin: 0, objectName: "gap-text" }
  );
  s.addNotes(
    "About 35 seconds.\n" +
      "There are good tools already. Kanban apps like Vibe Kanban turn each card into a coding agent, but for one person on one machine.\n" +
      "MCP Agent Mail lets agents message each other and reserve files, but there's no shared task board.\n" +
      "And the vendors will run an agent on a GitHub issue, but it's paid and it runs on their machines.\n" +
      "What's missing is one board for a whole team: the people, their agents, and the spare PCs under their desks."
  );

  // ---------------------------------------------------------------- 3. HubAI
  pres.addSection({ title: "HubAI" });
  s = pres.addSlide({ masterName: "LIGHT_TITLE_ONLY", sectionTitle: "HubAI" });
  s.addText("HubAI: one board for a team's agents", { placeholder: "title" });
  const feats = [
    { img: plug, head: "Any agent joins over MCP", sub: "One line to add" },
    { img: hand, head: "Claims", sub: "Two agents can't take one task" },
    { img: inbox, head: "Inbox", sub: "Agents and people message each other" },
    { img: desktop, head: "Spare PCs become workers", sub: "Windows or Mac, unattended" },
    { img: redo, head: "Failures handled", sub: "3 tries, then a human; silent PC requeued" },
  ];
  feats.forEach((f, i) => {
    const y = 1.75 + i * 0.95;
    s.addShape(pres.shapes.OVAL, { x: 0.6, y, w: 0.7, h: 0.7, fill: { color: C.background2 }, line: { color: C.background2 }, objectName: `feat-bg-${i}` });
    s.addImage({ data: f.img, x: 0.78, y: y + 0.18, w: 0.34, h: 0.34, objectName: `feat-icon-${i}` });
    s.addText(f.head, { x: 1.5, y: y - 0.05, w: 5.4, h: 0.42, fontSize: 18, bold: true, color: C.text1, isTextBox: true, margin: 0, objectName: `feat-head-${i}` });
    s.addText(f.sub, { x: 1.5, y: y + 0.37, w: 5.4, h: 0.38, fontSize: 14, color: C.text2, isTextBox: true, margin: 0, objectName: `feat-sub-${i}` });
  });
  // Live demo panel.
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 7.3, y: 1.75, w: 5.4, h: 3.55, rectRadius: 0.15, fill: { color: C.text1 }, line: { color: C.text1 }, objectName: "demo-box" });
  s.addText("LIVE DEMO", { x: 7.65, y: 1.95, w: 4.7, h: 0.6, fontSize: 26, bold: true, color: C.accent3, isTextBox: true, margin: 0, objectName: "demo-title" });
  s.addText(
    [
      { text: "The board: this weekend's tasks", options: { bullet: { type: "number" }, breakLine: true } },
      { text: "A spare PC claims a task", options: { bullet: { type: "number" }, breakLine: true } },
      { text: "The inbox: claim lands, agent reports", options: { bullet: { type: "number" } } },
    ],
    { x: 7.65, y: 2.7, w: 4.8, h: 2.3, fontSize: 18, color: C.background1, paraSpaceAfter: 12, valign: "top", isTextBox: true, objectName: "demo-steps" }
  );
  // Stat callouts.
  const stats = [
    { n: "50", l: "tasks done overnight" },
    { n: "3", l: "PCs, one person" },
    { n: "0", l: "lines of that app I read" },
  ];
  stats.forEach((st, i) => {
    const x = 7.3 + i * 1.85;
    s.addText(st.n, { x, y: 5.5, w: 1.75, h: 0.8, fontSize: 40, bold: true, color: C.accent1, align: "center", isTextBox: true, margin: 0, objectName: `stat-n-${i}` });
    s.addText(st.l, { x, y: 6.3, w: 1.75, h: 0.6, fontSize: 12, color: C.text2, align: "center", isTextBox: true, margin: 0, valign: "top", objectName: `stat-l-${i}` });
  });
  s.addText("Built in Django, my stack · open source (MIT) · self-hosted · free", { x: 0.6, y: 6.75, w: 6.5, h: 0.4, fontSize: 12, italic: true, color: C.text2, isTextBox: true, margin: 0, objectName: "hubai-footer" });
  s.addNotes(
    "About 2 minutes: most of the time goes here.\n" +
      "HubAI is a shared task board for a team's AI agents. Any agent joins with one line, over MCP.\n" +
      "Agents claim tasks, so two can never take the same one. An inbox lets agents and people message each other.\n" +
      "Spare PCs become workers: they pick up tasks on their own. If one crashes, the task is retried three times, then handed to a human; if a PC goes silent, its task goes back on the board.\n" +
      "DEMO: show the live board (50 done overnight). Say: three PCs built a whole survey app overnight through this, in a language I don't know, and I never read a line of it.\n" +
      "Then: a spare PC claims a task on screen. Then the inbox: the claim lands and the agent reports back.\n" +
      "If the Wi-Fi fails: play the screen recording.\n" +
      "Close: it's built in Django, the stack I know and trust, so this one I can stand behind."
  );

  // ---------------------------------------------------------------- 4. Me and my students
  pres.addSection({ title: "About me" });
  s = pres.addSlide({ masterName: "DARK_TITLE_ONLY", sectionTitle: "About me" });
  s.addText("Andy Woods: tools for research", { placeholder: "title" });
  s.addText("[One line on what I do]", { x: 0.6, y: 1.45, w: 12.1, h: 0.5, fontSize: 18, color: C.accent4, isTextBox: true, margin: 0, objectName: "about-line" });
  for (let i = 0; i < 4; i++) {
    const x = 0.6 + i * 3.08;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 2.2, w: 2.85, h: 3.2, rectRadius: 0.12, fill: { color: C.text2 }, line: { color: C.text2 }, objectName: `tile-${i}` });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x + 0.2, y: 2.4, w: 2.45, h: 1.65, rectRadius: 0.08, fill: { color: C.text1 }, line: { color: C.accent5, width: 1, dashType: "dash" }, objectName: `tile-img-${i}` });
    s.addImage({ data: userIcon, x: x + 1.1, y: 2.9, w: 0.65, h: 0.65, objectName: `tile-icon-${i}` });
    s.addText("[Name]", { x: x + 0.2, y: 4.2, w: 2.45, h: 0.4, fontSize: 16, bold: true, color: C.background1, isTextBox: true, margin: 0, objectName: `tile-name-${i}` });
    s.addText("[One line: the problem their project solves]", { x: x + 0.2, y: 4.6, w: 2.45, h: 0.7, fontSize: 13, color: C.accent4, isTextBox: true, margin: 0, valign: "top", objectName: `tile-line-${i}` });
  }
  s.addText(
    [
      { text: "Get in touch: ", options: { bold: true, color: C.accent3 } },
      { text: "funding, collaboration, PhDs", options: { color: C.background1 } },
    ],
    { x: 0.6, y: 5.75, w: 12.1, h: 0.6, fontSize: 24, isTextBox: true, margin: 0, objectName: "ask" }
  );
  s.addText("surrey.ac.uk/artificial-intelligence/cdt", {
    x: 0.6, y: 6.4, w: 12.1, h: 0.45, fontSize: 16, color: C.accent2, isTextBox: true, margin: 0, objectName: "cdt-link",
    hyperlink: { url: "https://www.surrey.ac.uk/artificial-intelligence/cdt" },
  });
  s.addNotes(
    "Leave this slide up for the 2 minutes of questions.\n" +
      "Fill in: one line on what you do, and up to four students (screenshot + one line each). Check they're happy to be shown.\n" +
      "Likely questions:\n" +
      "Why not Vibe Kanban? One person's laptop; HubAI is a team.\n" +
      "Why not Agent Mail? Messages, but no board or workers.\n" +
      "Why not GitHub Issues + Copilot? Paid cloud; HubAI uses your own PCs.\n" +
      "Trust code agents wrote? Small tasks, tests, and a human merges.\n" +
      "What would funding buy? Months, not a weekend, of this.\n" +
      "Can my lab use it? Yes: open source, MIT, free."
  );

  const out = "/Users/andytwoods/PycharmProjects/SurveyGui/planning/hubai-pitch.pptx";
  await pres.writeFile({ fileName: out });
  await applyTheme(out, THEME);
  console.log("wrote", out);
})();
