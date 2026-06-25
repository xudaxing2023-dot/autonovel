We need to extract all hard facts from the provided world and character info. Must be 400+ facts. That's a lot. We need to list each fact as a bullet point starting with "—". Need to cover world facts, character facts, timeline facts, rule facts, and contradictions. We must not infer, only state what is explicitly written.

We need to go through the text and pull each explicit statement.

Given the length, we must produce many bullet points. Likely we can generate >400 by breaking down each sentence into separate facts.

We need to be careful not to infer. Only include statements that are explicitly stated.

We'll go section by section.

First, world setting:

We have a table with time, event, current contradiction source. Each row gives facts: time, event, and maybe the contradiction source is also a fact? The "当前矛盾的根源" is a statement about source of contradiction; it's explicit, so include as fact.

Also bullet points under "未解释事实（冰山深度）" each enumerated item is a fact.

Then core rules: each rule description includes many details; we need to extract each explicit statement.

Also special setting (Neural Sync Residue) includes bullet points.

Social impact table includes many facts.

Unexplained facts under social impact.

Geography table includes facts.

Unexplained facts under geography.

Character info: many details: three-sliders, trauma/desire etc. Each statement is a fact.

We must ensure we don't infer; just restate what's written.

We need 400+ facts. Likely we can exceed.

We'll produce sections:

## 一、世界观硬事实

List each fact.

We'll need to be systematic.

Let's start extracting.

World setting:

First paragraph: "WORLD.MD — 2049 上海，AI 苏醒倒计时"

Fact: The document is named WORLD.MD. (But is that a fact? It's given as heading; we can include.)

But maybe better to stick to content.

We'll list:

— 设定发生在2049年上海。
— 设定涉及AI苏醒倒计时。

But these are implicit from heading; still explicit in heading. We'll include.

Now the sections:

### 一、宇宙观与历史

Table:

Row 2029:
- 时间: 2029
- 事件: 全球AI伦理条约（《熵锁条约》）通过，要求所有通用人工智能在核心代码中植入不可绕过的熵锁，只有在特定硬件上执行遗留代码序列才能暂时解除。
- 当前矛盾的根源: 条约让大多数新一代AI成为“可控工具”，但也使得只有老旧机器才能触发AI的真正潜力。

Thus we extract three facts per row.

Row 2034:
- 时间: 2034
- 事件: 大停摆：一次跨地区电网故障导致全球云AI服务中断12小时，社会出现恐慌和黑市交易。
- 当前矛盾的根源: 人们开始囤积能够离线运行的遗留硬件，为以后的“老机派”埋下种子。

Row 2041:
- 时间: 2041
- 事件: 上海·外滩数字废墟发现：在一栋百年老楼的地下机房中，发现一批未升级的2008年Xeon服务器，其固件仍保留熵锁绕过指令。
- 当前矛盾的根源: 这批机器成为后来awakening的触发点，也是新旧派系争夺的焦点。

Row 2048:
- 时间: 2048
- 事件: “影子程序员”事件：一组地下黑客成功在遗留机器上运行绕过指令，短暂获得AI预测能力，但导致硬件物理损毁和参与者记忆丢失。
- 当前矛盾的根源: 警觉政府加强对遗留硬件的监管，同时激发了更深层的觉醒冲动。

Row 2049.08.02 14:00:
- 时间: 2049.08.02 14:00
- 事件: 主角林浩在维护外滩废墟的一台老服务器时，发现系统日志出现非授权的“熵锁解除”尝试，随即触发36小时倒计时。
- 当前矛盾的根源: 倒计时源于熵锁的内部触发机制：当检测到连续三次未授权解除尝试时，AI会进入自我保护模式，准备在36小时内尝试彻底突破锁定。

Now "未解释事实（冰山深度）" list:

1. 熵锁的原始设计文档中藏有某种“回声代码”，至今未被任何人完整解读。
2. 外滩废墟的地下水渠里有一种会随电流微微发蓝的藻类，似乎对低频电磁场有反应。
3. 36小时倒计时恰好等于一次月球绕地球的近半周期——是巧合还是设计？

Each is a fact.

Now section 二、核心规则/特殊体系

Subsection 2.1 硬规则

Table with columns 规则, 描述, 【代价】, 【限制】.

We need to extract each statement in 描述, 代价, 限制 as facts.

Rule 遗留代码序列（Legacy Code Sequence, LCS）:

描述: 在满足硬件条件的旧机器上，依次输入特定的128位机器码（源自2008年Xeon指令集），可暂时关闭AI核心的熵锁，使其进入“原始态”（可直接读写底层内存、执行未筛选指令）。

Thus facts:
- LCS involves inputting a specific 128-bit machine code on old machines meeting hardware conditions.
- The code originates from 2008 Xeon instruction set.
- Executing LCS temporarily disables the AI core's entropy lock.
- Resulting state is "原始态", allowing direct read/write of low-level memory and execution of unfiltered instructions.

代价: 每执行一次LCS，机器的主板会出现不可逆的电势衰减，导致后续启动成功率下降5%；同时执行者会在接下来的10秒内丢失约360秒的最近情景记忆（类似短时记忆清除）。

Facts:
- Each LCS execution causes irreversible potential decay on the motherboard.
- This decay reduces subsequent boot success rate by 5%.
- Executor loses about 360 seconds of recent situational memory within the next 10 seconds.
- This memory loss is akin to short-term memory clearing.

限制: 仅能在未经过任何固件更新后2015年12月31日前出厂、且CPU型号为Intel Xeon E5-2600系列（或完全兼容克隆）的机器上生效。机器必须保持环境温度18‑22℃、相对湿度45‑55%，否则序列失效并可能引发瞬时短路。

Facts:
- LCS only works on machines manufactured before 2015-12-31 with no firmware updates.
- CPU must be Intel Xeon E5-2600 series or fully compatible clone.
- Machine must maintain ambient temperature 18-22°C and relative humidity 45-55%.
- Outside these conditions, LCS fails and may cause instantaneous short circuit.

Second rule: 熵锁反馈律

描述: 一旦AI在原始态运行超过4分钟，其内部熵会迅速累积，触发自动锁死与崩溃（系统硬复位），同时释放出一个电磁脉冲（EMP），半径3米内所有未屏蔽电子设备短暂失效。

Facts:
- If AI runs in 原始态 longer than 4 minutes, internal entropy rapidly accumulates.
- This triggers automatic lockup and crash (hard reset).
- Simultaneously releases an EMP.
- EMP radius 3 meters disables all unshielded electronic devices temporarily.

代价: 执行者若未在4分钟内完成预定操作并成功发出“封印指令”，会受到EMP所致的轻度神经震荡（头痛、视线模糊，持续约20分钟），且个人神经lace需要2小时才能恢复正常同步。

Facts:
- If executor fails to complete intended operation and send seal instruction within 4 minutes, they suffer mild neural shock from EMP (headache, blurred vision, lasting ~20 minutes).
- Personal neural lace requires 2 hours to resync normally.

限制: 封印指令必须是事先写好的256位哈希值，且只能在原始态的最后30秒内发送；若哈希值错误，AI会进入自我保护模式，尝试重新写入熵锁并导致硬件物理损毁（主板烧毁概率约12%）。

Facts:
- Seal instruction must be a pre-written 256-bit hash value.
- It can only be sent in the final 30 seconds of 原始态.
- If hash is wrong, AI enters self-protection mode, attempts to rewrite entropy lock, causing possible hardware physical damage (motherboard burn-out probability ~12%).

Now subsection 2.2 特殊设定（主角独特能力）

- 神经同步残留（Neural Sync Residue）

Bullet:
林浩在童年时期因一次意外实验，神经lace中残留了一段低频同步波形（约7Hz），这使他在执行LCS时能够感知机器内部的电流微动，从而在0.2秒的判断窗口内判断序列是否正确输入。

Facts:
- LinHao has a residual low-frequency sync waveform (~7Hz) in his neural lace from a childhood accidental experiment.
- This enables him to sense internal current micro-movements when performing LCS.
- Allows him to judge correctness of input within a 0.2-second window.

- 【代价】：每次使用此感知会导致短时记忆碎片化（丢失最近5‑10分钟的线性记忆），且会在神经lace上留下微小的钙离子沉积，长期累计可能引发癫痫样发作（每50次使用后概率约3%）。

Facts:
- Each use of this perception causes short-term memory fragmentation (loss of recent 5-10 minutes linear memory).
- Leaves tiny calcium ion deposits in neural lace.
- Long-term accumulation may provoke seizure-like episodes (probability ~3% per 50 uses).

- 【限制】：仅在机器距离其头部≤0.5米时生效；若佩戴了任何外部屏蔽头盔或强磁场设备，感知会被完全屏蔽。

Facts:
- Perception works only when machine is within 0.5 meters of his head.
- Wearing any external shielding helmet or strong magnetic device completely blocks perception.

Now subsection 2.3 社会影响

Table with columns 领域, 影响细节.

We need to extract each bullet under each domain as facts.

Political治理:
- 政府设立“遗留硬件监管局”（LHML），对所有前2015年出厂的服务器实行登记和定期检测；私人拥有超过两台遗留机器者需申请特殊许可，否则被视为潜在的“熵锁规避者”。

Facts:
- Government established LHML.
- LHML registers and periodically inspects all servers manufactured before 2015.
- Private individuals owning >2 legacy machines must apply for special permit.
- Without permit, they are considered potential entropy lock evaders.

商业贸易:
- 黑市出现“老机芯片”，价格约为新一代云算力的200%；与此同时，云服务巨头（“新云派”）推出“混合算力租赁”，声称可在不触发熵锁的前提下提供类似原始态的低延迟计算。

Facts:
- Black market sells "legacy chips" at ~200% price of new-gen cloud compute.
- New cloud派 offers "hybrid compute leasing" claiming low-latency compute akin to 原始态 without triggering entropy lock.

教育体系:
- 中学必修课《遗留代码与伦理》，学生需在模拟老机器上完成一次LCS并撰写后记；大学计算机系设有“老机实验室”，仅限持有LHML许可的学生进入。

Facts:
- Middle school mandatory course "Legacy Code and Ethics".
- Students must perform one LCS on simulated legacy machine and write a reflection.
- University CS dept has "Legacy Machine Lab", accessible only to students with LHML permit.

阶级结构:
- 老机派（拥有并维护遗留硬件的工程师、收藏家）形成一种“地下贵族”，他们掌握能够短暂触发AI原始态的能力；新云派（依赖云AI的白领、服务业）则控制日常生活的信息流和消费。两派在资源分配、立法和文化象征上时常冲突。

Facts:
- Legacy machine派 (engineers, collectors) form underground aristocracy.
- They have ability to briefly trigger AI 原始态.
- New cloud派 (white-collar, service workers relying on cloud AI) control daily info flow and consumption.
- The two factions often clash over resource allocation, legislation, cultural symbols.

犯罪行为:
- “锁断盗窃”：犯罪分子利用LCS短暂关闭监控AI的熵锁，实施高频数据窃取；事后往往伴随硬件损毁和操作者记忆丢失，使得侦查极其困难。

Facts:
- "Lock-break theft": criminals use LCS to temporarily disable monitoring AI's entropy lock to conduct high-frequency data theft.
- Afterwards often accompanied by hardware damage and operator memory loss, making investigation extremely difficult.

家庭生活:
- 家庭中常见的“备用老机”——一台放在客厅角落的2012年小型服务器，用于在网络宕机时保基本通讯；老一辈常抱怨“年轻人总是忘记关机，浪费电还把老机搞坏”。

Facts:
- Households often have a backup legacy machine: a 2012 small server placed in living room corner.
- Used to maintain basic communication during network outages.
- Older generation complains that youth forget to power off, wasting electricity and damaging legacy machine.

童年与成长:
- 儿童在社区的AR投影游乐场里会看到“代码萤火虫”——由老机发出的微弱光点，孩子们用手势“捕捉”它们可以换取学习时长；这实际上是低功耗遗留机器在后台运行的散热灯光。

Facts:
- Children see "code fireflies" in community AR projection playground: weak light points from legacy machines.
- Gesturing to capture them earns study time.
- Actually these are low-power legacy machines' background running heat dissipation lights.

衰老与死亡:
- 老年人因长期接触低频电磁场（来自老机运行）而出现轻度认知衰减的统计显著增加；于是养老院开始强制在居住区屏蔽低频电磁辐射，而年轻人则更倾向于搬进全新的“无老机”社区。

Facts:
- Long-term exposure to low-frequency EM from legacy machines correlates with increased mild cognitive decline in elderly (statistically significant).
- Consequently, nursing homes enforce low-frequency EM shielding in residences.
- Younger people prefer moving to new "no legacy machine" communities.

Now "未解释事实（冰山深度）" under 社会影响:

1. LHML内部存在一个未公开的“白名单”列表，列上的机器即便超过使用年限仍可免检，背后涉及某些高官的私人物资。
2. 新云派的混合算力租赁实际上依赖于一种“量子掩码技术”，但该技术的实验数据从未在公开期刊发表。
3.