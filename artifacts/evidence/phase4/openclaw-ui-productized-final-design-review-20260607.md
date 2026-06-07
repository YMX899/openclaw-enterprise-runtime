# OpenClaw UI Productized Final Design Review

Date: 2026-06-07 Asia/Shanghai

Reviewer role: visual communication design director, final UI evidence review

## 审查范围

本次审查只使用当前 root UI productized acceptance 证据作为最终判断依据：

- Desktop screenshot: `D:\DESK\Dify\artifacts\evidence\phase4\openclaw-ui-productized-root-desktop-20260607.png`
- Mobile screenshot: `D:\DESK\Dify\artifacts\evidence\phase4\openclaw-ui-productized-root-mobile-20260607.png`
- Acceptance JSON: `D:\DESK\Dify\artifacts\evidence\phase4\openclaw-ui-productized-root-acceptance-20260607.json`

未使用旧 public/workbench 截图作为最终判断。未修改代码，未部署，未进行本地测试。本文不记录账号、密码、cookie、headers、token 或原始视频链接。

工程理解：OpenClaw Lab 是一个短视频分析操作台，核心路径是独立登录、创建分析会话、提交视频来源、查看 worker 进度和模型分析结果，同时保留诊断与验收信息，供操作者在同一个产品界面完成端到端任务。它不是普通 demo 页，而应被视为一个可信、可重复使用、可交付的专业工具表面。

验收 JSON 显示 desktop/mobile 均通过 productized acceptance：页面加载、工作流、source tabs、result cards、diagnostics、raw JSON secondary、必需 ID、登录、会话创建、post-login 16 项验收和无水平溢出均为 PASS。这证明功能与结构验收成立。以下审查专注于视觉沟通、状态可信度、布局成熟度和产品化观感。

## 总体结论

当前 UI 已从工程测试页进入可识别的产品化操作台形态：页面标题明确，五步流程存在，表单和结果区域完整，desktop 与 mobile 都没有明显横向溢出，移动端主流程可完整访问。这是一个合格的 root acceptance UI，不再是散乱的临时 workbench。

但以顶级软件公司的视觉交付标准看，它还不能给 100/100。主要原因不是功能缺口，而是视觉状态叙事仍不够可信：截图中大量可见文案仍停留在 `Login required`、`Waiting`、`No source` 等前置状态，而验收 JSON 同时声明 Authenticated、Acceptance PASS、session ready。即使这是截图时机或状态刷新造成的证据差异，最终视觉证据层也会让审阅者产生“功能已过但界面没有同步表达成功”的疑问。其次，移动端纵向成本偏高、CTA 优先级重复、诊断区域和用户任务争夺注意力、品牌系统仍较基础。

最终分数：84/100。

当前状态审核结论：有条件通过，可作为本轮 root productized acceptance 的视觉证据归档；不建议标记为视觉 100/100 或“最终客户级抛光完成”。若要进入无保留视觉签核，需要先完成本文“必须修改项”。

## 20 个问题与结论

| # | 问题 | 证据观察 | 设计结论 | 优先级 |
|---|---|---|---|---|
| 1 | 验收状态与截图可见状态不完全一致 | JSON 显示 Authenticated、Acceptance PASS、session ready；截图顶部和结果卡仍显示 Login required、Waiting、No source | 最终视觉证据必须让机器验收状态与人眼状态一致，否则可信度被削弱 | P0 |
| 2 | 顶部重复红色登录提示造成噪声 | Desktop 和 mobile 顶部各出现两个相似的 Login required pill | 登录状态应是单一、稳定、可解释的系统状态，不应重复制造警报感 | P1 |
| 3 | 步骤导航的当前态表达偏弱 | 五步条中 Login 明显高亮，但后续 Session/Source 等实际区域也可见且可操作 | 需要区分 done/current/locked/error，避免流程看起来既未开始又允许继续 | P1 |
| 4 | 主 CTA 的优先级过于平均 | Login、Create Session、Analyze Video 均使用强蓝主按钮 | 同一屏多个强主按钮会稀释下一步动作，应随流程动态突出唯一主行动 | P1 |
| 5 | 桌面左右栏空间利用不均衡 | 左列很长，右侧结果卡之后有大量空白 | 右侧状态区应具备 sticky、摘要、最近结果或工作流上下文价值，否则桌面宽屏利用率不足 | P2 |
| 6 | 移动端开头信息过重 | 标题、两个红色状态、五个步骤条之后才进入登录卡 | 移动首屏应尽快进入当前任务，流程导航可压缩为更轻的进度组件 | P1 |
| 7 | 诊断与验收区域位置过于靠前 | Mobile 中 Diagnostics & Acceptance 位于 Conversation 与 Result 之间 | 对普通操作者，诊断应退居 secondary；对验收人员，可折叠但不应打断主任务叙事 | P2 |
| 8 | 结果区状态卡重复表达 | Result & Status 内 Analysis/Source/Result 与 Auth/Job/Output 重复描述等待和登录状态 | 状态仪表盘需要合并层级：用户结果、任务状态、技术诊断应分层 | P1 |
| 9 | 告警色语义过重 | 未登录状态使用红色 pill，但页面并未显示真正错误或失败 | 红色应保留给失败、危险或阻断；待登录更适合中性或蓝灰提示 | P1 |
| 10 | 文案大小写与语气不一致 | Login required、Login Required、No job yet、Waiting 混合使用 | 产品级 UI 需要统一大小写和语气，降低“拼装界面”观感 | P2 |
| 11 | 品牌识别仍然很薄 | 只有 OC 黑色方标和 OpenClaw Lab 标题，缺少更完整的视觉识别系统 | 作为独立产品表面，需要更明确的品牌节奏、图标语言和状态色系统 | P2 |
| 12 | 卡片权重过于一致 | Login、Session、Video Source、Conversation、Result 卡片视觉重量接近 | 当前步骤、已完成步骤、辅助步骤应有不同视觉层级 | P1 |
| 13 | 表单启用/禁用关系不够清晰 | 未完成登录/会话时，后续输入和 Analyze Video 仍呈现可行动状态 | 操作台必须通过禁用、锁定、说明或自动承接表现依赖关系 | P1 |
| 14 | Link/Upload 分段控件较基础 | 分段控件可用，但 mobile 中像普通双按钮，状态语义不够精致 | 来源选择是关键分叉，应有更清晰的选中态、说明和错误承接 | P2 |
| 15 | Conversation 面板缺少真实对话感 | 绿色提示框和 Prompt textarea 形成静态表单感，而非 worker conversation | 如果保留 conversation，应区分 system/user/worker，强化进度和结果回流 | P2 |
| 16 | Raw JSON 入口仍偏显眼 | Sanitized JSON response 位于结果卡底部，虽然折叠但仍在主结果框内 | 技术 payload 应作为高级诊断入口，避免普通结果体验被工程细节打断 | P2 |
| 17 | 字体层级偏工程化 | 标题、卡片标题、标签、说明文字清晰但缺少更细的层级控制 | 当前可读，但高级产品感不足；需要更精确的 type scale 和说明文字密度 | P2 |
| 18 | 边框和阴影语言略同质 | 大量浅边框、浅阴影、浅蓝灰底形成单一材质 | 需要通过层级、背景 band、状态色和局部强调建立更成熟的视觉节奏 | P2 |
| 19 | 移动端按钮堆叠造成操作疲劳 | Login/Logout/Refresh、Check/Analyze/Refresh 在 mobile 上连续满宽堆叠 | 次要操作应降级为 ghost、icon 或 overflow，主路径保留一个高显著 CTA | P1 |
| 20 | 可访问性仍需视觉层确认 | 小号说明文字、圆形编号、浅色辅助文本在截图中可读但余量有限 | 下一轮应补充对比度、焦点态、错误态和触控间距的视觉验收 | P2 |

## 评分表

| 维度 | 权重 | 得分 | 评价 |
|---|---:|---:|---|
| 产品目的与信息架构 | 15 | 13 | 短视频分析操作台的结构已经成立，五步工作流和结果区可理解 |
| 工作流清晰度与状态建模 | 15 | 11 | 主路径完整，但 done/current/locked/pass/fail 的状态表达还不够成熟 |
| 桌面构图与视觉层级 | 15 | 13 | 双栏布局稳定，卡片清晰；右栏空白和卡片同权重削弱高级感 |
| 移动端适配与触控体验 | 13 | 12 | 无横向溢出，控件可点；首屏信息过重和按钮堆叠需要压缩 |
| 交互暗示与 CTA 优先级 | 12 | 10 | 按钮清楚，但多个主 CTA 并存，依赖关系和禁用状态表达不足 |
| 字体、间距与内容密度 | 12 | 11 | 整体干净可读，局部说明文字偏多，移动端密度仍可优化 |
| 品牌与视觉系统成熟度 | 10 | 8 | 已有基础品牌锚点，但图标、色彩、状态和材质系统仍偏初级 |
| 信任感、诊断呈现与证据一致性 | 8 | 6 | JSON 验收强，但截图状态与 PASS 叙事不完全一致，是最终视觉签核的主要扣分项 |
| **总分** | **100** | **84** | **有条件通过，不是 100/100** |

## 必须修改项

如果目标是 100/100 视觉签核，必须至少完成以下修改：

1. 统一最终证据中的 UI 状态表达：当验收 JSON 显示 Authenticated、Acceptance PASS、session ready 时，截图可见界面也必须清楚表达同一状态。
2. 合并顶部重复登录提示，建立单一全局状态栏或状态 badge，避免双红色警报。
3. 为五步流程建立明确的 done/current/locked/error/pass 状态模型，并与表单可用性同步。
4. 降低非当前步骤 CTA 的视觉权重，确保每个阶段只有一个清晰主动作。
5. 优化 mobile 首屏：压缩流程导航和状态提示，让用户更快进入当前任务。
6. 将 Diagnostics、Acceptance、Raw JSON 等工程信息降级为可展开的高级区域，不打断普通任务流。
7. 合并结果区重复状态卡，区分“用户结果摘要”“任务运行状态”“技术诊断”三层信息。
8. 建立更完整的色彩与状态语义：红色只用于失败或危险，等待/未开始/需登录使用中性或提示色。
9. 统一 UI 文案大小写和语气，避免同一概念多种写法。
10. 补充可访问性视觉验收，包括对比度、焦点态、错误态和触控目标稳定性。

## 最终审核结论

当前 OpenClaw UI 通过了 root productized acceptance 的功能和结构验收，也具备了专业工具界面的基本形态。作为工程验收证据，它可以归档为“有条件通过”。

但从视觉传达设计总监视角，当前状态不是满分交付。扣分集中在最终证据的人眼可信度、状态叙事、移动端信息压缩、CTA 优先级和诊断信息分层。若必须给出最终商业级视觉签核，结论是：84/100，Conditional PASS；完成上述必须修改项后，才可重新评估是否达到 100/100。
