# 技能治理:SkillOS 於 nemofleet(worker-c 當 curator)

_已實作。改編自 **SkillOS**(arXiv 2605.06614,_"Learning Skill Curation for Self-Evolving Agents"_)。_

SkillOS 把一個 **frozen executor**(取用技能解任務)配一個 **trainable curator**(以 insert/update/delete 管理可重用的 Markdown 技能庫),用複合 reward(任務成效、操作合法性、內容品質、**抗膨脹/精簡**)+ 便宜的 **BM25 檢索**訓練 curator。

nemofleet 本就以 **Markdown + YAML frontmatter** 存技能(`skills/*`)、把 eval lessons 沉澱成技能 —— 與 SkillOS 同格式。我們把 curator 的**品質閘 + BM25 檢索**落地,交給 **worker-c**(它已是變更治理官,治理艦隊的程序記憶是自然延伸)。**無 RL 訓練環境 → 用確定性閘 + LLM 擴充**取代 reward。

## 對應

| SkillOS | nemofleet |
|---|---|
| executor(取用技能) | team-lead / worker-a / worker-b(跑 `SKILL.md`) |
| curator(管理技能庫) | **worker-c**(zone C `curate` cap) |
| 技能 = Markdown + YAML frontmatter | `skills/*`(本來就是) |
| 品質 reward(內容 / 合法 / 抗膨脹) | `wi_skills` 確定性閘 + LLM 擴充 |
| BM25 檢索 | `wi_skills.bm25_search` |
| RL 訓練 curator(GRPO + 複合 reward) | 不做(無訓練環境)→ 確定性閘取代 |

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

## 接進自我進化
**已接上**:`lessons-to-skill.sh` / `skill-sync.sh` 落地/散播技能前呼叫 `lib/common.sh` 的 `skill_gate()` → worker-c `POST /skill-review`;**reject = 綁定不落地**(帶 required_fixes 退回);worker-c 未部署則放行+提示(gate-if-available)。技能庫因此**受治理、抗膨脹、人可稽核**,不再無限堆積;判決可進稽核鏈。executor(team-lead/a/b)用 `GET /skills?q=` 找技能。

## 沙箱實測(已驗)
worker-c(zone C)對真實 `skills/`(12 支)curating:`GET /skills` 列出;`?q=review worker quality` 的 BM25 first-hit = `review-gate`;insert 好技能 → approve、無 frontmatter → reject;delete 不存在 → reject;A2A `curate` 可用。單元測試涵蓋 parse / 品質閘 / 抗膨脹 / BM25 / delete。

## 與論文的差異(誠實)
SkillOS 的核心貢獻是 **RL 訓練 curator**(GRPO + 複合 reward,學會何時 insert/update/delete);我們**沒有訓練環境**,落地的是它可直接用、可測、可稽核的部分:**確定性品質閘 + BM25 檢索 + 抗膨脹**,把需要判斷的「內容品質 / 根因」留給 team-lead / worker-c 的 LLM 擴充。人可稽核的 Markdown 技能格式兩邊一致。未來若接上 eval 成效訊號,可朝「以下游成效自動調整 curation 門檻」演進。
