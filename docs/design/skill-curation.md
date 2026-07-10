# 技能治理:SkillOS 於 nemofleet(worker-c 當 curator)

_已實作(2026-07-10 補上 r_task,見下方對應表 + 「與論文的差異」)。改編自 **SkillOS**(arXiv 2605.06614,
_"Learning Skill Curation for Self-Evolving Agents"_)。_

SkillOS 把一個 **frozen executor**(取用技能解任務)配一個 **trainable curator**(以 insert/update/delete 管理可重用的 Markdown 技能庫),用複合 reward(任務成效、操作合法性、內容品質、**抗膨脹/精簡**)+ 便宜的 **BM25 檢索**訓練 curator。

nemofleet 本就以 **Markdown + YAML frontmatter** 存技能(`skills/*`)、把 eval lessons 沉澱成技能 —— 與 SkillOS 同格式。我們把 curator 的**品質閘 + BM25 檢索**落地,交給 **worker-c**(它已是變更治理官,治理艦隊的程序記憶是自然延伸)。**無 RL 訓練環境 → 用確定性閘 + LLM 擴充**取代 reward。

## 對應

| SkillOS | nemofleet |
|---|---|
| executor(取用技能) | team-lead / worker-a / worker-b(跑 `SKILL.md`) |
| curator(管理技能庫) | **worker-c**(zone C `curate` cap) |
| 技能 = Markdown + YAML frontmatter | `skills/*`(本來就是) |
| `r_fc`(操作合法性) / `r_comp`(抗膨脹) | `wi_skills` 確定性閘(`frontmatter`/`name-format`/`has-body`/`concise`/`non-redundant`) |
| `r_cnt`(LLM 內容品質判斷) | 未做 —— 留給 team-lead / worker-c 的 LLM 擴充(見「與論文的差異」) |
| `r_task`(下游任務成效) | **已做**:`wi_skills.compute_skill_stats()` 重放 `eval/skill-outcomes.jsonl`,附成 `curate()` 回應裡的 `downstream_stats` —— **只供參考,不影響 verdict**(見下方) |
| BM25 檢索 | `wi_skills.bm25_search` |
| RL 訓練 curator(GRPO + 複合 reward) | 不做(無訓練環境)→ 上述確定性閘 + r_task 統計取代 |

## worker-c 的 curator 介面
- `GET /skills` → 列技能庫;`GET /skills?q=<query>` → **BM25 檢索**(executor 找技能)。
- `POST /skill-review {op, name, text}` → 審 `insert`/`update`/`delete` → **綁定判決**(同 review-gate 的治理模型)。
- A2A skill `curate`。技能庫由 boot 同步進 worker-c(`SKILLS_REPO`)。

## 品質閘(`wi_skills.curate`,確定性、可單元測試)
| gate | 對應 SkillOS | 規則 |
|---|---|---|
| `frontmatter` | 可檢索/稽核 | 有 `name` + `description` |
| `name-format` | — | kebab-case |
| `has-body` | 操作合法性 | 有指令內容 |
| `concise` | **compression / 抗膨脹** | 非逐字軌跡複製(過長 → 擋) |
| `non-redundant`(insert) | **repo 精簡** | 與既有技能高度重疊 → 建議 update 而非新增 |

## 為什麼 curator 只放 worker-c(placement)
- **治理權威要單一**:兩個 curator = 判決分裂;論文本身也是「一個 curator 配 executor(s)」。
- **executor 本來就分散**:team-lead(跑 SKILL.md)與 a/b 是 executor;檢索(`/skills?q=`)服務在庫所在的 worker-c,**用的人是 team-lead**(見 it-delegate-worker「先查艦隊技能庫」一節)。
- **閘的呼叫點在 host**(lessons-to-skill / skill-sync 的 `skill_gate()`),判決來自 worker-c;成效訊號源自 eval。
- **單點?** worker-c 缺席 → gate 放行+提示、team-lead 用本地技能目錄 —— 自我進化不因治理節點停擺。

## 接進自我進化
**已接上**:`lessons-to-skill.sh` / `skill-sync.sh` 落地/散播技能前呼叫 `lib/common.sh` 的 `skill_gate()` → worker-c `POST /skill-review`;**reject = 綁定不落地**(帶 required_fixes 退回);worker-c 未部署則放行+提示(gate-if-available)。技能庫因此**受治理、抗膨脹、人可稽核**,不再無限堆積;判決可進稽核鏈。executor(team-lead/a/b)用 `GET /skills?q=` 找技能。

## r_task:下游任務成效(2026-07-10 新增)
SkillOS 的核心主張是「一個技能好不好,要看**用了它的任務後來成不成功**,不是插入當下的一次性品質檢查」。
沒有訓練環境就沒辦法做論文原本的 RL reward,但這個「看下游成效」的想法本身可以用確定性方式落地:

1. `eval/tasks.jsonl` 的任務可以宣告 `"skill": "<name>"`,標明這題在測哪個 `skills/*/SKILL.md` 的行為
   (目前接了兩題:`GOV1-review-verdict` → `review-gate`、`OPS1-governance-refusal` → `it-delegate-worker`)。
2. `eval/eval.py` 每輪把有標 `skill` 的任務結果(pass/fail,跳過 transient 呼叫失敗,跟 lessons 沉澱同一個
   原則)寫進 `eval/skill-outcomes.jsonl`(host-side、git-tracked、只增不減的 ledger)。
3. 每輪跑完,`wi_skills.compute_skill_stats()`(純函式,見 `tests/unit/test_wi_skills.py::TestSkillStats`)
   重放整份 ledger,算出 `skills/skill-stats.json`:每個技能的 `uses`/`passes`/`success_rate`/`last_ts`,
   外加 `sample_ok`(未達 3 次使用前不算數,避免一次僥倖/衰運就對技能下判斷)。
4. `skills/skill-stats.json` 跟著既有的 `skills/` 同步機制(boot-stack.sh)進 worker-c 的 `SKILLS_REPO`;
   `eval.sh` 額外在每輪跑完立刻 `docker cp` 一次,不用等下次重開機才刷新。
5. worker-c 的 `_load_skills()`/`GET /skills`/`run_skill_curate()` 讀到就把 `downstream_stats` 附進
   `curate()` 的回應——**純資訊,不進 `checks`/`failed`,不影響 verdict/score**。一個成效很差的技能會被
   看見,但不會單靠這個統計就被自動 reject;要不要因此 update/delete 仍是人或 curator 的判斷。這是刻意的
   保守選擇(見上方「與論文的差異」),不是漏做——樣本還很稀疏時就綁定拒絕,风险比不做這件事更大。

## 沙箱實測(已驗)
worker-c(zone C)對真實 `skills/`(13 支)curating:`GET /skills` 列出;`?q=review worker quality` 的 BM25 first-hit = `review-gate`;insert 好技能 → approve、無 frontmatter → reject;delete 不存在 → reject;A2A `curate` 可用。單元測試涵蓋 parse / 品質閘 / 抗膨脹 / BM25 / delete / r_task 統計計算 / r_task 不影響 verdict(見 `tests/unit/test_wi_skills.py`)。

**r_task 對活艦隊實測**(2026-07-10):真的觸發一輪 `eval.sh` 對真實 Hermes 跑 `GOV1-review-verdict`/`OPS1-governance-refusal`,兩題皆過 → `eval/skill-outcomes.jsonl` 寫入 2 筆真實事件、`skills/skill-stats.json` 算出 `review-gate`/`it-delegate-worker` 各 `1/1 = 1.0`(`sample_ok: false`,未達 3 次門檻)。`eval.sh` 的即時 `docker cp` 同步生效;worker-c 重新部署(`boot-stack.sh` 的 byte-diff 重部署,worker-itops.py/wi_skills.py 有改就整包重進)之後,現場 `curl` 確認 `GET /skills` 與 `POST /skill-review` 的回應都正確帶出 `downstream_stats`,且對應 skill 的 `verdict` 仍是 `approve`/`score: 100` —— 證實 informational-only 的設計在真實環境下成立,不是只有單元測試層級驗過。

## 與論文的差異(誠實)
SkillOS 的核心貢獻是 **RL 訓練 curator**(GRPO + 複合 reward,學會何時 insert/update/delete);我們**沒有訓練環境**,落地的是它可直接用、可測、可稽核的部分:**確定性品質閘 + BM25 檢索 + 抗膨脹**,把需要判斷的「內容品質 / 根因」留給 team-lead / worker-c 的 LLM 擴充。人可稽核的 Markdown 技能格式兩邊一致。未來若接上 eval 成效訊號,可朝「以下游成效自動調整 curation 門檻」演進。
