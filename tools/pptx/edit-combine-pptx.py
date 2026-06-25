#!/usr/bin/env python3
# edit-combine-pptx.py — 就地把 A/B/C 建議改進使用者編輯版 combine pptx(保留其版式)。
import copy
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

F = "ASUS-NemoClaw-Competition-2026-combine.pptx"
prs = Presentation(F)
JHENG = "Microsoft JhengHei"
NAVY = RGBColor(0x0B, 0x2A, 0x4A); GREEN = RGBColor(0x00, 0x84, 0x6C); BLUE = RGBColor(0x00, 0x58, 0x9E)
INK = RGBColor(0x11, 0x18, 0x27); GRAY = RGBColor(0x64, 0x74, 0x8B); GRAY2 = RGBColor(0x94, 0xA3, 0xB8)
SKY = RGBColor(0x7D, 0xD3, 0xFC); LIGHT = RGBColor(0xF7, 0xF9, 0xFC); LINE = RGBColor(0xE2, 0xE8, 0xF0)
CBD = RGBColor(0xCB, 0xD5, 0xE1); WHITE = RGBColor(0xFF, 0xFF, 0xFF)


def setfont(r, size, color, bold, font=JHENG):
    r.font.size = Pt(size); r.font.bold = bold; r.font.name = font; r.font.color.rgb = color
    rPr = r._r.get_or_add_rPr()
    for tag in ("latin", "ea", "cs"):
        e = rPr.find(qn("a:" + tag))
        if e is None:
            e = rPr.makeelement(qn("a:" + tag), {}); rPr.append(e)
        e.set("typeface", font)


def sh(slide, j): return slide.shapes[j]
S = prs.slides

# ── A3 typo (slide5[4]) ──
r = sh(S[4], 4).text_frame.paragraphs[0].runs[0]
r.text = r.text.replace("一台被默默的路由器", "一台被默默改壞的路由器")

# ── A2 scoped 通道 box restore /32+token (slide6[15]) ──
shp = sh(S[5], 15)
tf = shp.text_frame
# keep existing run as line2, prepend line1
old = tf.paragraphs[0].runs[0]
old.text = "/32 + token"
p2 = tf.add_paragraph(); p2.alignment = tf.paragraphs[0].alignment
r2 = p2.add_run(); r2.text = "唯一跨代理路徑"; setfont(r2, 9.5, GRAY, False)
shp.height = Inches(0.7)

# ── A1 reword 巡檢 line + (offline framing) (slide9[7] p1) ──
p1 = sh(S[8], 7).text_frame.paragraphs[1]
p1.runs[0].text = "OpenClaw 巡檢設備 + 掃 CVE(離線比對,不需連外)"
p1.runs[1].text = "→ 機隊逐台分級,affected 才走治理 egress 升級"

# ── A2 restore /32+token 雙鎖 on bottom line (slide9[12]) ──
b = sh(S[8], 12).text_frame.paragraphs[0].runs[0]
b.text = ("OPA 引擎在 host / path / binary 三層程式碼級強制;跨代理通道再加 /32 + token 雙鎖"
          " —— 危險動作在設計層就做不出來。")

# ── C7 restore closing "現在就在跑" line (slide11[6] empty box) ──
box = sh(S[10], 6).text_frame
box.word_wrap = True
p = box.paragraphs[0]
r = p.add_run(); r.text = "這套系統現在就在跑:一句話報修、44 秒修復、修不了自動升級工程師,全程可稽核。"
setfont(r, 13.5, CBD, False)

# ── C6 re-add comparison table on slide7 empty middle ──
s = S[6]
x0, y0, rh = 0.62, 2.02, 0.6
colx = [x0, x0 + 4.3, x0 + 8.2]; colw = [4.3, 3.9, 12.1 - 8.2]
rows = [
    ("", "人工(現況)", "雙代理(本系統)"),
    ("發現設備設定退化", "靠定期巡檢,可能整季漏看", "比對已核准 baseline,當下抓出"),
    ("報修 → 修復完成", "報修→轉單→排工程師,以天/週計", "一句話 → 自動修,實測 44 秒"),
    ("修復範圍判斷", "人逐項判斷該不該動", "只修安全退化,漂移自動列待審"),
    ("修不了的案子", "信件往返、容易卡住", "自動開 Jira 工單升級工程師"),
    ("機隊規模", "台數越多越做不完", "多台 OpenClaw,邊際人力 ≈ 0"),
]


def addrect(l, t, w, h, fill=None, line=None, lw=1.0):
    shp = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(l), Inches(t), Inches(w), Inches(h))
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid(); shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line; shp.line.width = Pt(lw)
    shp.shadow.inherit = False
    return shp


def addtext(l, t, w, h, text, size, color, bold, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE):
    tb = s.shapes.add_textbox(Inches(l), Inches(t), Inches(w), Inches(h))
    tf = tb.text_frame; tf.word_wrap = True; tf.vertical_anchor = anchor
    tf.margin_left = Pt(3); tf.margin_right = Pt(3); tf.margin_top = Pt(1); tf.margin_bottom = Pt(1)
    p = tf.paragraphs[0]; p.alignment = align
    r = p.add_run(); r.text = text; setfont(r, size, color, bold)
    return tb


for ri, row in enumerate(rows):
    yy = y0 + ri * rh
    if ri == 0:
        addrect(x0, yy, 12.1, rh, fill=NAVY)
        addtext(colx[1], yy, colw[1], rh, row[1], 12.5, GRAY2, True, PP_ALIGN.CENTER)
        addtext(colx[2], yy, colw[2], rh, row[2], 12.5, SKY, True, PP_ALIGN.CENTER)
    else:
        if ri % 2 == 0:
            addrect(x0, yy, 12.1, rh, fill=LIGHT)
        addtext(colx[0] + 0.12, yy, colw[0] - 0.18, rh, row[0], 11.5, INK, True)
        addtext(colx[1] + 0.08, yy, colw[1] - 0.16, rh, row[1], 11, GRAY, False, PP_ALIGN.CENTER)
        addtext(colx[2] + 0.08, yy, colw[2] - 0.16, rh, row[2], 11, GREEN, True, PP_ALIGN.CENTER)
addrect(x0, y0, 12.1, rh * len(rows), line=LINE, lw=1)
addrect(colx[2] - 0.02, y0, colw[2] + 0.02, rh * len(rows), line=GREEN, lw=1.5)

prs.save(F)
print("saved", F, "; slides", len(prs.slides._sldIdLst))
