"use strict";
const listRoot = document.getElementById("task-list");
const detailRoot = document.getElementById("task-detail");
const errorRoot = document.getElementById("error");
let selectedTaskRequest = 0;

function el(tag, value, klass) {
  const node = document.createElement(tag);
  if (value !== undefined && value !== null) node.textContent = String(value);
  if (klass) node.className = klass;
  return node;
}
function add(parent, tag, value, klass) {
  const node = el(tag, value, klass);
  parent.append(node);
  return node;
}
function when(value) {
  if (typeof value === "number") return new Date(value / 1000).toLocaleString();
  if (typeof value === "string" && value) return new Date(value).toLocaleString();
  return "Hub 未留存";
}
async function api(path) {
  const response = await fetch(path, {cache: "no-store", credentials: "same-origin"});
  if (!response.ok) throw new Error("Hub 读取失败：" + response.status);
  return response.json();
}
function focusOn(node) {
  if (node && typeof node.scrollIntoView === "function") {
    node.scrollIntoView({behavior: "auto", block: "start"});
  }
}
function missing(parent, name) { add(parent, "p", name + "：Hub 未留存", "muted"); }
function artifact(parent, taskId, item, label) {
  if (!item) return missing(parent, label);
  const row = add(parent, "div", null, "artifact");
  add(row, "span", label + " · " + item.id + " · " + item.size_bytes + " B");
  const path = "/control/api/tasks/" + encodeURIComponent(taskId) +
    "/artifacts/" + encodeURIComponent(item.id);
  const button = add(row, "button", "查看");
  button.type = "button";
  button.addEventListener("click", async () => {
    let output = row.querySelector("pre");
    if (!output) output = add(row, "pre", "");
    try { output.textContent = (await api(path + "/preview")).text; }
    catch (_) { output.textContent = "内容不可预览；可能包含受限内容或超出大小限制。"; }
  });
  const link = add(row, "a", "下载");
  link.href = path;
  link.download = item.id + ".bin";
}
function review(parent, value, label) {
  if (!value) return missing(parent, label);
  add(parent, "h3", label);
  add(parent, "p", value.summary || "Hub 未留存");
  if (value.blocker_category) add(parent, "p", "阻断类别：" + value.blocker_category);
  if (value.timestamp) add(parent, "p", "Reviewer 声明时间：" + when(value.timestamp), "muted");
  for (const [key, title] of [["comments","原文意见"],["suggestions","建议"],
                              ["recommendations","建议"],["risks","风险"],
                              ["findings","Finding"],["proposed_changes","修改建议"],
                              ["evidence","证据"],["verifications","Finding 验证"]]) {
    const values = value[key] || [];
    if (!values.length) continue;
    add(parent, "h3", title);
    const ul = add(parent, "ul");
    for (const item of values) {
      const text = typeof item === "string" ? item :
        [item.title, item.finding, item.description, item.impact,
         item.recommendation, item.mitigation, item.rationale, item.reason,
         item.evidence, ...(item.proposed_changes || [])].filter(Boolean).join(" · ");
      add(ul, "li", text);
    }
  }
}
function packageBox(parent, taskId, item) {
  if (!item) return missing(parent, "交付包");
  add(parent, "h3", "终审 R" + item.round + " 产物");
  if (item.operation_method) add(parent, "pre", item.operation_method);
  else missing(parent, "操作方法");
  add(parent, "h3", "生成文件");
  if (!item.generated_files.length) missing(parent, "逐文件内容");
  for (const file of item.generated_files) artifact(parent, taskId, file.artifact, file.path);
  if (item.changed_files.length) add(parent, "p", "变更文件名：" + item.changed_files.join("、"));
  if (item.diff) artifact(parent, taskId, item.diff, "代码差异");
  else missing(parent, "代码差异");
  add(parent, "h3", "测试结果");
  if (!item.tests.length) missing(parent, "测试结果原文");
  for (const test of item.tests) artifact(parent, taskId, test, "WorkBuddy 提交的测试");
  if (item.self_test) add(parent, "p", "自测：" + item.self_test.status +
      " · " + item.self_test.summary);
  for (const risk of item.known_risks || []) add(parent, "p", "已知风险：" + risk);
  for (const gap of item.unverified_items || []) add(parent, "p", "未验证：" + gap);
}
async function timeline(parent, taskId, visibleArtifacts) {
  add(parent, "h2", "完整时间线");
  const entries = add(parent, "div");
  const more = add(parent, "button", "加载时间线");
  more.type = "button";
  let cursor = null;
  async function load() {
    const suffix = cursor ? "?cursor=" + encodeURIComponent(cursor) : "";
    const data = await api("/control/api/tasks/" + encodeURIComponent(taskId) + "/events" + suffix);
    for (const event of data.events) {
      const row = add(entries, "div", null, "row");
      add(row, "span", when(event.at) + " · " + event.actor_type + " · " + event.action);
      if (event.old_state || event.new_state) add(row, "span", " · " +
          (event.old_state || "") + " → " + (event.new_state || ""));
      if (event.request_id) add(row, "span", " · " + event.request_id);
      if (event.metadata) {
        add(row, "span", " · " + Object.entries(event.metadata)
            .map(([name, value]) => name + ": " + value).join(" · "));
        const item = visibleArtifacts.get(event.metadata.artifact_id);
        if (item) artifact(row, taskId, item, "Hub 原始内容");
      }
    }
    cursor = data.next_cursor;
    more.hidden = !cursor;
  }
  more.addEventListener("click", () => load().catch(e => errorRoot.textContent = e.message));
  await load();
}
async function showTask(taskId) {
  const request = ++selectedTaskRequest;
  errorRoot.textContent = "";
  detailRoot.classList.remove("loaded");
  detailRoot.classList.add("loading");
  detailRoot.replaceChildren();
  add(detailRoot, "h2", "Task 详情");
  add(detailRoot, "p", "正在加载 Task 详情…", "loading-status");
  focusOn(detailRoot);
  let data;
  try {
    data = await api("/control/api/tasks/" + encodeURIComponent(taskId));
  } catch (e) {
    if (request !== selectedTaskRequest) return;
    detailRoot.classList.remove("loading");
    detailRoot.replaceChildren();
    errorRoot.textContent = "读取失败：" + e.message;
    focusOn(errorRoot);
    return;
  }
  if (request !== selectedTaskRequest) return;
  detailRoot.classList.remove("loading");
  detailRoot.classList.add("loaded");
  detailRoot.replaceChildren();
  const task = data.task;
  add(detailRoot, "h2", "Task 详情 · " + task.id);
  add(detailRoot, "p", "已加载 Task 详情", "success-status");
  add(detailRoot, "p", "Hub 状态：" + task.state + " · 创建：" + when(task.created_at));
  if (task.completion_basis) add(detailRoot, "p",
      task.completion_basis === "HUMAN_OVERRIDE" ?
      "Human override · 完成依据：HUMAN_OVERRIDE" :
      "完成依据：" + task.completion_basis);
  if (task.gate_reason) add(detailRoot, "p", "Gate 原因：" + task.gate_reason);
  artifact(detailRoot, taskId, task.original_task, "Human 原始需求");
  if (data.plan_r2_blocked) {
    const box = add(detailRoot, "section", null, "blocked");
    add(box, "h2", data.plan_r2_blocked.active ?
        "方案 R2 BLOCKED · 等待 Human" : "历史方案 R2 BLOCKED");
    artifact(box, taskId, data.plan_r2_blocked.plan_v1, "方案 V1");
    review(box, data.plan_r2_blocked.grok_r1,
        (data.plan_r2_blocked.r1_reviewer_label || "Reviewer") + " R1 原文");
    artifact(box, taskId, data.plan_r2_blocked.plan_v2, "方案 V2");
    review(box, data.plan_r2_blocked.r2_reason,
        (data.plan_r2_blocked.r2_reviewer_label || "Reviewer") + " R2 阻断理由");
  }
  if (data.final_r2_blocked) {
    const box = add(detailRoot, "section", null, "blocked");
    add(box, "h2", data.final_r2_blocked.active ?
        "终审 R2 BLOCKED · 未验收通过" : "历史终审 R2 BLOCKED · 曾未验收通过");
    packageBox(box, taskId, data.final_r2_blocked.package);
    review(box, data.final_r2_blocked.r2_reason,
        (data.final_r2_blocked.r2_reviewer_label || "Reviewer") + " R2 阻断理由");
  }
  const rounds = add(detailRoot, "section");
  add(rounds, "h2", "方案与审核");
  if (!data.rounds.length) missing(rounds, "审核轮次");
  for (const item of data.rounds) {
    const box = add(rounds, "article");
    add(box, "h3", (item.type === "PLAN_REVIEW" ? "方案" : "终审") +
        " R" + item.round + " · " + item.label);
    add(box, "p", "RR：" + item.id + " · Hub 创建：" + when(item.created_at) +
        " · 生效：" + when(item.hub_applied_at));
    if (item.failure_code) add(box, "p", "技术原因：" + item.failure_code, "warning");
    artifact(box, taskId, item.input, "审核输入");
    review(box, item.review, (item.reviewer_label || "Reviewer") + " 文案");
  }
  const messages = add(detailRoot, "section");
  add(messages, "h2", "WorkBuddy 文案");
  if (!data.workbuddy_messages.length) missing(messages, "独立业务消息原文");
  for (const item of data.workbuddy_messages) {
    const box = add(messages, "article");
    add(box, "h3", item.stage + " · " + when(item.created_at));
    add(box, "pre", item.body);
  }
  const products = add(detailRoot, "section");
  add(products, "h2", "代码、操作方法、测试与文件");
  if (!data.packages.length) missing(products, "终审产物");
  for (const item of data.packages) packageBox(products, taskId, item);
  const human = add(detailRoot, "section");
  add(human, "h2", "Human 决策");
  if (!data.human_decisions.length) missing(human, "Human 决策");
  for (const item of data.human_decisions) {
    add(human, "p", (item.kind || "决定") + " · " + item.status +
        " · " + when(item.decision_at));
    if (item.reason) artifact(human, taskId, item.reason, "Human 理由");
  }
  const visible = new Map();
  function remember(item) { if (item) visible.set(item.id, item); }
  remember(task.original_task);
  for (const item of data.rounds) remember(item.input);
  for (const item of data.workbuddy_messages) remember(item.artifact);
  for (const item of data.packages) {
    remember(item.diff);
    for (const test of item.tests) remember(test);
    for (const file of item.generated_files) remember(file.artifact);
  }
  for (const item of data.human_decisions) remember(item.reason);
  focusOn(detailRoot);
  try {
    await timeline(add(detailRoot, "section"), taskId, visible);
  } catch (e) {
    if (request === selectedTaskRequest) {
      add(detailRoot, "p", "时间线读取失败：" + e.message, "warning");
    }
  }
}
async function loadList() {
  const data = await api("/control/api/tasks");
  listRoot.replaceChildren();
  add(listRoot, "h2", "最近 Task");
  for (const task of data.tasks) {
    const row = add(listRoot, "div", null, "row");
    const button = add(row, "button", task.id, "link");
    button.type = "button";
    button.addEventListener("click", () =>
        showTask(task.id).catch(e => errorRoot.textContent = e.message));
    add(row, "span", " · " + task.state + " · " + when(task.created_at));
  }
}
document.getElementById("search").addEventListener("submit", event => {
  event.preventDefault();
  showTask(document.getElementById("task-id").value.trim())
      .catch(e => errorRoot.textContent = e.message);
});
loadList().catch(e => errorRoot.textContent = e.message);
