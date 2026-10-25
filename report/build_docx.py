"""生成《ReasoningBank 代码复现报告》Word 文档（A4、目录、图表编号、页眉页脚）。

两遍生成：第一遍目录页码用占位符，用 Word 量出各标题实际页码后，
第二遍读取 pages.json 写入真实页码（TOC 行数不变，因此分页不会漂移）。
"""

import argparse
import json
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT, WD_TAB_LEADER
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "report_assets"
OUT = HERE / "ReasoningBank_代码复现报告.docx"

parser = argparse.ArgumentParser()
parser.add_argument("--pages", default=None, help="由第一遍生成后量出的 JSON：{标题: 页码}")
args = parser.parse_args()
PAGES = json.loads(Path(args.pages).read_text(encoding="utf-8")) if args.pages else {}

# 目录条目（与正文 add_heading 的文本严格一致）
HEADINGS = [
    (1, "1　引言"),
    (2, "1.1　研究背景"),
    (2, "1.2　复现目标与约束"),
    (2, "1.3　主要工作与结论"),
    (1, "2　原始代码分析"),
    (2, "2.1　系统结构"),
    (2, "2.2　单任务的三阶段流程"),
    (2, "2.3　记忆条目的结构与注入方式"),
    (2, "2.4　关键设计取舍"),
    (2, "2.5　与 Google 技术栈的三处强耦合"),
    (1, "3　复现方案与实现"),
    (2, "3.1　总体思路"),
    (2, "3.2　运行环境"),
    (2, "3.3　代码改动"),
    (1, "4　实验与结果"),
    (2, "4.1　实验设置"),
    (2, "4.2　三轮迭代"),
    (2, "4.3　最终结果"),
    (2, "4.4　记忆注入审计"),
    (2, "4.5　定性观察"),
    (1, "5　讨论"),
    (2, "5.1　为何未观察到收益"),
    (2, "5.2　与论文设定的差异"),
    (2, "5.3　方法学教训"),
    (1, "6　工程困难与解决"),
    (1, "7　结论"),
    (1, "附录 A　关键命令"),
    (1, "附录 B　数据与脚本清单"),
]

SONG = "宋体"
HEI = "黑体"
MONO = "Consolas"
GRAY = RGBColor(0x59, 0x5F, 0x6B)
ACCENT = RGBColor(0x1F, 0x3B, 0x73)


# --------------------------------------------------------------------- 基础工具
def set_run_font(run, name=SONG, size=None, bold=None, color=None, italic=None):
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), name)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.font.bold = bold
    if italic is not None:
        run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color


def style_font(style, name, size, bold=False, color=None):
    style.font.name = name
    style.font.size = Pt(size)
    style.font.bold = bold
    if color is not None:
        style.font.color.rgb = color
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:eastAsia"), name)
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)


def para_border(paragraph, edge="bottom", sz=6, color="C9CED6"):
    ppr = paragraph._p.get_or_add_pPr()
    pbdr = ppr.find(qn("w:pBdr"))
    if pbdr is None:
        pbdr = OxmlElement("w:pBdr")
        ppr.append(pbdr)
    el = OxmlElement(f"w:{edge}")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(sz))
    el.set(qn("w:space"), "1")
    el.set(qn("w:color"), color)
    pbdr.append(el)


def add_field(paragraph, instr, placeholder="", size=9):
    run = paragraph.add_run()
    fld = OxmlElement("w:fldChar")
    fld.set(qn("w:fldCharType"), "begin")
    run._r.append(fld)

    run2 = paragraph.add_run()
    instr_el = OxmlElement("w:instrText")
    instr_el.set(qn("xml:space"), "preserve")
    instr_el.text = instr
    run2._r.append(instr_el)

    run3 = paragraph.add_run()
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    run3._r.append(sep)

    run4 = paragraph.add_run(placeholder)
    set_run_font(run4, SONG, size, color=GRAY)

    run5 = paragraph.add_run()
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run5._r.append(end)


# --------------------------------------------------------------------- 文档设置
doc = Document()

sec = doc.sections[0]
sec.page_width = Cm(21.0)
sec.page_height = Cm(29.7)
sec.left_margin = Cm(2.6)
sec.right_margin = Cm(2.6)
sec.top_margin = Cm(2.5)
sec.bottom_margin = Cm(2.4)
sec.header_distance = Cm(1.4)
sec.footer_distance = Cm(1.3)

normal = doc.styles["Normal"]
style_font(normal, SONG, 10.5)
normal.paragraph_format.line_spacing = 1.55
normal.paragraph_format.space_before = Pt(0)
normal.paragraph_format.space_after = Pt(4)

for name, size in (("Heading 1", 16), ("Heading 2", 13.5), ("Heading 3", 11.5)):
    st = doc.styles[name]
    style_font(st, HEI, size, bold=True, color=RGBColor(0, 0, 0))
    st.paragraph_format.space_before = Pt(14 if name == "Heading 1" else 10)
    st.paragraph_format.space_after = Pt(6)
    st.paragraph_format.line_spacing = 1.3
    st.paragraph_format.keep_with_next = True

# 让 Word 打开时自动更新页码等域（目录为静态文本，不受影响）
settings = doc.settings.element
update = OxmlElement("w:updateFields")
update.set(qn("w:val"), "true")
settings.append(update)


def add_toc(pages: dict) -> None:
    """静态目录：标题 + 点线前导 + 页码（无域，Word/WPS 打开即正确）。"""
    for level, text in HEADINGS:
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(7 if level == 1 else 0)
        pf.space_after = Pt(2)
        pf.line_spacing = 1.15
        pf.left_indent = Cm(0 if level == 1 else 1.1)
        pf.tab_stops.add_tab_stop(Cm(15.6), WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS)
        r = p.add_run(text)
        set_run_font(r, HEI if level == 1 else SONG, 10.5, bold=(level == 1))
        r2 = p.add_run("\t" + str(pages.get(text, "00")))
        set_run_font(r2, SONG, 10.5, bold=(level == 1))


def body(text, indent=True, size=10.5, space_after=4):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    if indent:
        p.paragraph_format.first_line_indent = Pt(size * 2)
    r = p.add_run(text)
    set_run_font(r, SONG, size)
    return p


def bullet(text, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.left_indent = Cm(0.9)
    r = p.add_run(text)
    set_run_font(r, SONG, size)
    return p


def caption(text, before=True):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6 if before else 2)
    p.paragraph_format.space_after = Pt(4 if before else 8)
    p.paragraph_format.keep_with_next = before
    r = p.add_run(text)
    set_run_font(r, SONG, 9, color=GRAY)
    return p


def add_table(headers, rows, widths, font_size=9, header_size=9):
    # 页面正文宽度 15.8cm，宽度按比例归一化，避免表格溢出
    total = sum(widths)
    widths = [w * 15.6 / total for w in widths]

    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    # 固定列宽布局
    tblpr0 = table._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblpr0.append(layout)
    tblw = OxmlElement("w:tblW")
    tblw.set(qn("w:type"), "dxa")
    tblw.set(qn("w:w"), str(int(15.6 * 567)))
    tblpr0.append(tblw)

    for i, w in enumerate(widths):
        table.columns[i].width = Cm(w)

    # 三线表边框
    tbl = table._tbl
    tblpr = tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge, sz in (("top", 12), ("bottom", 12)):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(sz))
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "1A1A1A")
        borders.append(el)
    for edge in ("left", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "none")
        el.set(qn("w:sz"), "0")
        el.set(qn("w:space"), "0")
        borders.append(el)
    tblpr.append(borders)

    def fill_cell(cell, text, bold=False, size=font_size):
        cell.text = ""
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing = 1.15
        r = p.add_run(text)
        set_run_font(r, HEI if bold else SONG, size, bold=bold)

    hdr = table.rows[0]
    # 长表格跨页时重复表头
    trpr = hdr._tr.get_or_add_trPr()
    th = OxmlElement("w:tblHeader")
    trpr.append(th)
    for i, h in enumerate(headers):
        fill_cell(hdr.cells[i], h, bold=True, size=header_size)
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), "EDF1F7")
        hdr.cells[i]._tc.get_or_add_tcPr().append(shd)
        # 表头下横线
        tcpr = hdr.cells[i]._tc.get_or_add_tcPr()
        tcb = OxmlElement("w:tcBorders")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:color"), "1A1A1A")
        tcb.append(bottom)
        tcpr.append(tcb)

    for row in rows:
        cells = table.add_row().cells
        for i, val in enumerate(row):
            fill_cell(cells[i], val)

    for row in table.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Cm(w)

    # 表格不跨页断行
    for row in table.rows:
        trpr = row._tr.get_or_add_trPr()
        cant = OxmlElement("w:cantSplit")
        trpr.append(cant)
    return table


def add_figure(name, width_cm=15.6):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.keep_with_next = True
    p.add_run().add_picture(str(ASSETS / name), width=Cm(width_cm))


def add_code(lines):
    for line in lines:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.05
        p.paragraph_format.left_indent = Cm(0.4)
        r = p.add_run(line if line else " ")
        set_run_font(r, MONO, 8.5)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


# --------------------------------------------------------------------- 页眉页脚
sec.different_first_page_header_footer = True  # 封面不显示页眉页脚

header_p = sec.header.paragraphs[0]
header_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
hr = header_p.add_run("ReasoningBank 代码复现报告")
set_run_font(hr, SONG, 9, color=GRAY)
para_border(header_p, "bottom", sz=4, color="D6DBE3")

footer_p = sec.footer.paragraphs[0]
footer_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r0 = footer_p.add_run("— ")
set_run_font(r0, SONG, 9, color=GRAY)
add_field(footer_p, " PAGE ", "1")
r1 = footer_p.add_run(" —")
set_run_font(r1, SONG, 9, color=GRAY)

# --------------------------------------------------------------------- 封面
for _ in range(3):
    doc.add_paragraph()

t = doc.add_paragraph()
t.alignment = WD_ALIGN_PARAGRAPH.CENTER
t.paragraph_format.space_after = Pt(10)
tr = t.add_run("ReasoningBank 代码复现报告")
set_run_font(tr, HEI, 26, bold=True, color=ACCENT)

st = doc.add_paragraph()
st.alignment = WD_ALIGN_PARAGRAPH.CENTER
st.paragraph_format.space_after = Pt(6)
sr = st.add_run("从 Gemini/Vertex 到 DeepSeek + 本地向量模型的完整迁移与实验分析")
set_run_font(sr, HEI, 13, color=RGBColor(0x33, 0x38, 0x42))

st2 = doc.add_paragraph()
st2.alignment = WD_ALIGN_PARAGRAPH.CENTER
s2 = st2.add_run("—— 论文 ICLR 2026《ReasoningBank: Scaling Agent Self-Evolving with Reasoning Memory》")
set_run_font(s2, SONG, 10.5, color=GRAY)

for _ in range(6):
    doc.add_paragraph()

info = [
    ("复现对象", "reasoning-bank（Google Research，ICLR 2026）"),
    ("代码分支", "WebArena（网页智能体）+ SWE-Bench（软件工程智能体）"),
    ("运行环境", "Windows 11 + WSL2 Ubuntu 24.04 + Docker 29 + Python 3.12"),
    ("模型配置", "DeepSeek-chat（策略/裁判/记忆提炼）+ bge-m3（本地检索向量）"),
    ("实验规模", "shopping 站点 20 个任务 × 2 组 × 3 轮迭代"),
]
tbl = doc.add_table(rows=0, cols=2)
tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
for k, v in info:
    cells = tbl.add_row().cells
    cells[0].width = Cm(3.4)
    cells[1].width = Cm(10.4)
    p0 = cells[0].paragraphs[0]
    p0.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r = p0.add_run(k)
    set_run_font(r, HEI, 10.5, bold=True)
    p1 = cells[1].paragraphs[0]
    r = p1.add_run(v)
    set_run_font(r, SONG, 10.5)

for _ in range(6):
    doc.add_paragraph()

d = doc.add_paragraph()
d.alignment = WD_ALIGN_PARAGRAPH.CENTER
dr = d.add_run("2026 年 10 月")
set_run_font(dr, SONG, 11, color=GRAY)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
pr = p.add_run("姓名：__________　　学号：__________　　院系：__________")
set_run_font(pr, SONG, 10.5, color=GRAY)

doc.add_page_break()

# --------------------------------------------------------------------- 摘要
h = doc.add_paragraph()
h.alignment = WD_ALIGN_PARAGRAPH.CENTER
hr2 = h.add_run("摘　要")
set_run_font(hr2, HEI, 15, bold=True)
h.paragraph_format.space_after = Pt(10)

body(
    "本文对 ICLR 2026 论文《ReasoningBank: Scaling Agent Self-Evolving with Reasoning Memory》的公开实现进行了复现。"
    "该工作为网页智能体引入“推理记忆”机制：每个任务结束后，由大语言模型从交互轨迹中提炼结构化经验条目；"
    "后续任务到来时，以意图向量检索最相关的一条注入系统提示词，使智能体在成功与失败的轨迹中持续自我改进。",
)
body(
    "原始代码深度绑定 Google 技术栈：策略模型与裁判模型均通过 Vertex AI 调用 Gemini，检索向量依赖 gemini-embedding-001，"
    "且相关客户端在模块导入阶段即被创建。在仅有 OpenAI 兼容接口、无 GCP 凭据、且处于受限网络的条件下，代码无法直接运行。"
    "本文在不改动算法逻辑的前提下，构建了可切换的模型层与向量层：将策略、裁判与记忆提炼迁移至 DeepSeek，"
    "将检索向量迁移至本地 sentence-transformers 的 bge-m3；并在 WSL2 + Docker 环境中搭建 WebArena 购物站点，完成端到端复现。",
)
body(
    "实验共进行三轮对照。首轮出现页面导航超时导致的崩溃；次轮经注入审计发现记忆实际注入率为 0/20，对照无效；"
    "第三轮修复检索实现后注入率达到 20/20，两组任务成功率均为 50%（10/20，共 20 个任务），"
    "但记忆组平均步数由 6.4 上升至 8.2（+28%），两组在每一个任务上的成败判断完全一致。"
    "结果表明：记忆机制可被完整复现并在模型推理中被显式引用，但在该实验规模下未观察到成功率收益，且伴随明显的推理开销。"
    "本文同时记录了 29 项工程障碍及其解决方案，可作为同类智能体论文复现的参考。",
)
kw = doc.add_paragraph()
kw.paragraph_format.space_before = Pt(8)
r = kw.add_run("关键词：")
set_run_font(r, HEI, 10.5, bold=True)
r = kw.add_run("智能体记忆；WebArena；复现实验；提示词注入；可复现性")
set_run_font(r, SONG, 10.5)

# --------------------------------------------------------------------- 目录
doc.add_page_break()
h = doc.add_paragraph()
h.alignment = WD_ALIGN_PARAGRAPH.CENTER
hr3 = h.add_run("目　录")
set_run_font(hr3, HEI, 15, bold=True)
h.paragraph_format.space_after = Pt(6)

add_toc(PAGES)

doc.add_page_break()

# --------------------------------------------------------------------- 1 引言
doc.add_heading("1　引言", level=1)

doc.add_heading("1.1　研究背景", level=2)
body(
    "大语言模型智能体（LLM Agent）在网页操作、软件工程等任务上已具备可观的能力，但同类任务重复执行时，"
    "模型无法把上一轮的经验带到下一轮：每一次任务都从零开始试错。ReasoningBank 针对这一现象提出“推理记忆”范式，"
    "把轨迹抽象为可复用的经验条目，并在推理时按需检索，从而在不微调模型的前提下实现智能体的自我进化。",
)
body(
    "与早期“工作流记忆”（Agent Workflow Memory）只保存成功轨迹不同，ReasoningBank 同时利用成功与失败两类信号："
    "成功轨迹被提炼为“应当怎么做”，失败轨迹被提炼为“应当避免什么”，因此即使任务失败，也能产生可迁移的知识。",
)

doc.add_heading("1.2　复现目标与约束", level=2)
body(
    "本文的复现目标分为三层：其一是让代码在非 Google 技术栈上跑通；其二是验证记忆机制（提炼、检索、注入）确实生效；"
    "其三是在小规模任务集上对比有记忆与无记忆的成功率差异，并对结果作出解释。",
)
body("复现过程中受到三项现实约束，它们共同决定了技术路线：", indent=True)
bullet("算力与凭据：无 Google Cloud 项目与凭据，仅有 DeepSeek 的 OpenAI 兼容接口；")
bullet("网络：官方镜像与部分依赖的下载源在中国大陆不可达或已失效；")
bullet("平台：实验在 Windows 笔记本上进行，浏览器自动化与容器环境需借助 WSL2。")

doc.add_heading("1.3　主要工作与结论", level=2)
body("本文的主要工作包括：")
bullet("梳理原始实现的模块结构与数据流，定位三处与 Google 技术栈的强耦合点；")
bullet("实现可切换的模型层与向量层，使策略、裁判、记忆提炼与检索向量均可替换；")
bullet("在 WSL2 + Docker 上搭建 WebArena 购物站点，完成 20 个任务的端到端闭环；")
bullet("通过注入审计发现并修复了检索实现中的缺陷，最终获得一组有效的对照数据。")
body("主要结论是：记忆机制可完整复现并被模型显式引用；但在 20 个任务、单一站点的规模下，成功率无差异，推理开销上升约 28%。")

# --------------------------------------------------------------------- 2 源码分析
doc.add_heading("2　原始代码分析", level=1)

doc.add_heading("2.1　系统结构", level=2)
body(
    "仓库包含两条实验线：WebArena（网页智能体）与 SWE-Bench（软件工程智能体）。两者共享同一套记忆机制，"
    "差别仅在于“轨迹”的形态——前者是浏览器动作序列，后者是 shell 命令序列。表 1 列出主要模块及其职责。",
)
caption("表 1　源码模块与职责")
add_table(
    ["模块", "职责"],
    [
        ("WebArena/run.py", "执行单个任务：组装环境与智能体，检索记忆并注入提示词，记录每步观测与动作"),
        ("WebArena/pipeline_memory.py", "主循环：按站点筛选任务，依次调用 run.py、autoeval、induce_memory.py"),
        ("WebArena/induce_memory.py", "从轨迹中提炼记忆条目，按成功/失败选用不同提示词，写入 jsonl"),
        ("WebArena/memory_management.py", "记忆检索：计算意图向量相似度，返回 top-n 记忆"),
        ("WebArena/autoeval/", "LLM 裁判：判断轨迹是否完成目标，产出成功/失败信号"),
        ("WebArena/agents/legacy/", "网页智能体本体：提示词拼装、动作解析、历史压缩"),
        ("third_party/webarena/", "打过补丁的 WebArena 环境与评测器（标注修正、评测健壮性修复）"),
        ("third_party/src/minisweagent/", "裁剪版 mini-swe-agent，扩展了 memory/ 目录以复用同一记忆机制"),
    ],
    widths=[4.6, 11.0],
)

doc.add_heading("2.2　单任务的三阶段流程", level=2)
body(
    "对每个任务，主循环串行执行三个阶段。第一阶段由 run.py 完成“带记忆的推理”：读取任务意图，"
    "在历史意图向量中检索最相似的一条记忆，将其追加到系统提示词，然后驱动浏览器最多 30 步，"
    "并把每步的观测、思考与动作落盘为 step_N.pkl.gz。",
)
body(
    "第二阶段由 autoeval 完成“判分”：把任务目标、每步页面可访问性树文本、动作序列与最终回答交给裁判模型，"
    "输出成功或失败及理由。第三阶段由 induce_memory.py 完成“提炼”：根据判分结果选择“成功提示词”或“失败提示词”，"
    "让模型输出至多三条经验，按段落切分后连同任务意图、状态、模板编号一起追加到记忆库。",
)
body(
    "三个阶段构成一个闭环：本任务的记忆在第 N 步写入，第 N+1 个任务即可检索到它。"
    "由于检索只看意图相似度，记忆天然具有跨任务、跨模板的迁移能力，这也是该方法的卖点。",
)

doc.add_heading("2.3　记忆条目的结构与注入方式", level=2)
body("提炼出的每条记忆采用固定的三段式结构，以便检索后直接拼入提示词：")
add_code([
    "# Memory Item 1",
    "## Title        一句话标题",
    "## Description  什么情况下应当使用这条经验",
    "## Content      1—3 句可操作的建议",
])
body(
    "注入发生在前端提示词中：run.py 把检索结果写入 memories_<mode>/<site>.txt，智能体在每一步读取该文件，"
    "若非空，则在系统提示词后追加一段引导语与记忆正文。引导语要求模型“每一步先显式讨论是否采用每条记忆，再执行动作”，"
    "这一设计要求会显著增加推理长度，后文的实验结果将看到其代价。",
)

doc.add_heading("2.4　关键设计取舍", level=2)
caption("表 2　原始实现中的关键设计")
add_table(
    ["设计", "实现方式", "目的"],
    [
        ("四种记忆模式", "pipeline_memory.py 的 --memory_mode",
         "no_memory（对照）、reasoningbank（本文方法）、awm（仅学成功）、synapse（直接存原始轨迹）"),
        ("对错信号可切换", "--judge autoeval 或 gt",
         "autoeval 省人工但会误判；gt 使用官方评测器，信号准确但要求环境跑通"),
        ("检索仅用意图相似度", "memory_management.py 的 screening()", "无需额外分类器，可直接迁移到新任务"),
        ("模板编号仅记录", "写入 template_id 但未实现去重", "同模板任务的经验会重复堆积，影响提示词信息密度"),
        ("成功/失败双提示词", "prompts/memory_instruction.py", "失败轨迹同样能贡献知识，扩大记忆来源"),
    ],
    widths=[3.6, 5.4, 6.6],
)

doc.add_heading("2.5　与 Google 技术栈的三处强耦合", level=2)
body(
    "复现的第一个障碍并非算法，而是实现层面的强耦合。原代码在三处把 Google 客户端写在模块顶层或分支判断里，"
    "使得“换一个模型”必须改代码，而不是改配置。",
)
caption("表 3　三处与 Google 技术栈的强耦合点")
add_table(
    ["位置", "耦合形式", "后果"],
    [
        ("memory_management.py", "模块导入即执行 vertexai.init() 并创建 genai.Client(vertexai=True)",
         "无 GCP 凭据时，import 阶段直接失败，run.py 无法启动"),
        ("agents/legacy/utils/chat_api.py", "模型名以 gemini 前缀进入 ChatGemini 分支，其余名字落入写死 localhost:8000 的分支",
         "无法接入任意 OpenAI 兼容服务"),
        ("utils/clients.py、autoeval/clients.py", "CLIENT_DICT 仅注册 gpt/gemini/claude 三类客户端",
         "传入第三方模型名会直接 KeyError"),
        ("third_party/webarena/evaluation_harness/helper_functions.py", "模块导入即创建 Gemini 客户端用于 llm_fuzzy_match",
         "评测阶段再次因缺少 API key 崩溃"),
    ],
    widths=[5.0, 6.6, 4.0],
)

# --------------------------------------------------------------------- 3 复现方案
doc.add_heading("3　复现方案与实现", level=1)

doc.add_heading("3.1　总体思路", level=2)
body(
    "遵循“只换模型层、不动算法层”的原则：把散落在各处的模型调用收敛到一个新的提供者层，"
    "其余业务逻辑（提示词、动作解析、评测器、记忆格式）一律保持原样。这样既能在受限条件下跑通，"
    "也保证了实验结果与论文方法的可比性。",
)
caption("表 4　模型层替换对照")
add_table(
    ["层次", "原始实现", "本次复现"],
    [
        ("策略模型", "Gemini 2.5（Vertex AI）", "DeepSeek-chat（OpenAI 兼容接口）"),
        ("裁判模型", "Gemini 2.5 Pro", "DeepSeek-chat"),
        ("记忆提炼", "Gemini 2.5（Vertex AI）", "DeepSeek-chat"),
        ("检索向量", "gemini-embedding-001（3072 维）", "bge-m3（1024 维，本地推理）"),
        ("评测器", "Gemini 2.5 Pro + 官方评测脚本", "DeepSeek 判分 + 官方评测脚本"),
    ],
    widths=[3.4, 6.4, 5.8],
)

doc.add_heading("3.2　运行环境", level=2)
caption("表 5　运行环境构成")
add_table(
    ["组件", "版本/配置", "说明"],
    [
        ("宿主系统", "Windows 11", "笔记本，RTX 5060 8GB，32GB 内存"),
        ("Linux 子系统", "WSL2 + Ubuntu 24.04", "浏览器自动化与容器运行的实际环境"),
        ("容器运行时", "Docker Desktop 4.96（Engine 29）", "数据盘迁移至 D 盘，代理指向本机 7897 端口"),
        ("网页站点", "am1n3e/webarena-verified-shopping", "5.4GB 精简镜像，替代已失效的官方 45GB 镜像"),
        ("Python", "3.12.10（uv 管理）", "3.13 缺少 greenlet 3.0.3 轮子，故降级"),
        ("关键依赖", "browsergym 0.14.1、playwright 1.44、torch 2.14、sentence-transformers 6.2", "与仓库锁定版本一致"),
    ],
    widths=[3.4, 6.0, 6.2],
)

doc.add_heading("3.3　代码改动", level=2)
body(
    "共修改 14 处、新增 3 个模块与 7 个脚本。所有改动都围绕“让模型可替换、让环境可运行”，未触及记忆算法本身。"
    "表 6 列出主要改动及其动因。",
)
caption("表 6　代码改动清单")
add_table(
    ["文件", "改动", "动因"],
    [
        ("utils/reasoningbank_llm.py（新增）", "提供者层：OpenAI 兼容对话客户端 + 四种向量后端 + .env 加载",
         "原实现只认 Gemini/Vertex"),
        ("memory_management.py", "移除导入期初始化；向量后端可配置；缓存按维度过滤",
         "无 GCP 凭据时无法导入；换模型后维度不一致"),
        ("utils/clients.py、autoeval/clients.py", "新增 OPENAI_COMPAT_Client 与 get_client() 分发", "避免 KeyError"),
        ("evaluate_trajectory.py、induce_memory.py、pipeline_memory.py", "移除 --model 白名单；默认值取环境变量；子进程改用 sys.executable",
         "非内置模型名被 argparse 拒绝；子进程可能用错解释器"),
        ("agents/legacy/utils/chat_api.py", "增加“配置了环境变量即走兼容接口”分支", "原实现回落到写死 localhost 的分支"),
        ("agents/legacy/utils/llm_utils.py", "分词器加载失败时回退 tiktoken", "count_tokens 会把模型名当作 HF 仓库"),
        ("agents/legacy/dynamic_prompting.py", "系统提示词增加输出格式约束", "多行回答导致动作解析失败"),
        ("run.py", "默认模型取环境变量；输出长度上限可配置；补建记忆目录", "超长输出被服务端拒绝；目录缺失导致异常"),
        ("third_party/.../helper_functions.py", "裁判客户端改为惰性创建，优先兼容接口", "评测阶段因缺少 key 崩溃"),
        ("third_party/.../evaluators.py", "取页面内容前等待加载并重试", "页面跳转中读取 HTML 抛异常"),
        ("third_party/src/minisweagent/*", "同步向量与裁判改造；补建目录；模型名转义", "SWE-bench 分支同样硬编码 Gemini"),
        ("requirements.txt、requirements-swe.txt（新增）", "补齐未声明的依赖", "README 引用的文件不存在"),
        ("scripts/*（新增 7 个）", "环境安装、镜像拉取、体检、离线自检、批量运行、评分汇总、轨迹查看", "把排障经验固化为可复用脚本"),
    ],
    widths=[4.6, 6.4, 4.6],
    font_size=8.5,
)

# --------------------------------------------------------------------- 4 实验
doc.add_heading("4　实验与结果", level=1)

doc.add_heading("4.1　实验设置", level=2)
caption("表 7　实验参数")
add_table(
    ["参数", "取值", "说明"],
    [
        ("站点", "shopping（One Stop Shop）", "单站点落地，避免多容器资源开销"),
        ("任务数", "20（连续取 shopping 任务序列的前 20 个）", "包含两组同模板任务（评论检索类、订单统计类）"),
        ("记忆模式", "reasoningbank / no_memory", "实验组与对照组"),
        ("对错信号", "gt（官方评测器）", "避免 LLM 裁判误判带来的噪声"),
        ("步数上限", "30", "超出即截断记为失败"),
        ("检索条数", "1", "与论文默认设置一致"),
        ("每组重复", "1 次（共 3 轮迭代）", "受时间与 API 成本限制"),
    ],
    widths=[3.0, 6.6, 6.0],
)

doc.add_heading("4.2　三轮迭代", level=2)
body(
    "对照实验并非一次成功。首轮结果看似存在差异，但逐任务核查发现唯一差异来自页面加载超时；"
    "次轮在修复超时后再次得到差异，注入审计却显示实验组实际没有任何任务注入了记忆。"
    "第三轮修复检索缺陷后才得到有效数据。三轮结果见表 8。",
)
caption("表 8　三轮对照实验结果")
add_table(
    ["轮次", "实验组", "对照组", "有效性判断"],
    [
        ("第 1 轮（10 任务）", "7/10（70%）", "6/10（60%）", "无效：含页面导航超时崩溃"),
        ("第 2 轮（20 任务）", "12/20（60%）", "11/20（55%）", "无效：注入审计为 0/20"),
        ("第 3 轮（20 任务）", "10/20（50%）", "10/20（50%）", "有效：注入审计为 20/20"),
    ],
    widths=[4.2, 4.2, 4.2, 6.0],
)

doc.add_heading("4.3　最终结果", level=2)
body(
    "第三轮两组在每一个任务上的成败判断完全一致（零分歧），差异仅体现在过程开销上：记忆组平均 8.2 步，对照组 6.4 步。"
    "记忆组中有两个任务（124、126）跑满 30 步上限后被截断，对照组对应任务分别为 24 步与 4 步。",
)
caption("表 9　第三轮两组的成功率与步数")
add_table(
    ["指标", "reasoningbank", "no_memory", "差异"],
    [
        ("成功任务数", "10 / 20（50%）", "10 / 20（50%）", "0"),
        ("平均步数", "8.2", "6.4", "+1.8（+28%）"),
        ("跑满步数上限的任务", "2（124、126）", "0", "—"),
        ("判断不一致的任务数", "0", "0", "—"),
        ("记忆注入覆盖率", "20 / 20", "0 / 20（按设计）", "—"),
    ],
    widths=[4.4, 4.4, 4.4, 4.0],
)
add_figure("fig1_success.png")
caption("图 1　三轮实验的成功率对比", before=False)
add_figure("fig2_steps.png")
caption("图 2　第三轮两组的任务步数分布", before=False)

doc.add_heading("4.4　记忆注入审计", level=2)
body(
    "为确认记忆机制是否真正介入推理，本文编写了注入审计脚本：读取每个任务首步的系统提示词，"
    "检索“Below are some memory items”引导语与记忆条目数。审计发现两个问题：",
)
bullet("第二轮实验中，20 个任务全部未注入记忆。根因是检索函数先把当前任务的意图向量写入缓存、再以缓存为候选做相似度计算，"
       "使“自己检索自己”的相似度恒为 100%；而当前任务的记忆需在其运行结束后才写入记忆库，故检索必然落空。")
bullet("缓存中同一任务存在重复记录（缓存未在轮次间清理），进一步放大了上述效应。")
body(
    "修复方式为：缓存读取时按任务编号去重、保留最新记录；检索时排除当前任务自身的编号。"
    "修复后第三轮注入率达到 20/20，每个任务均携带 3 条记忆进入提示词。",
)
caption("表 10　注入审计样例（第三轮，实验组）")
add_table(
    ["任务", "注入", "记忆条数", "首条记忆标题"],
    [
        ("21", "是", "3", "Check the total review count before scanning content"),
        ("22", "是", "3", "Exhaust all review pages before concluding"),
        ("48", "是", "3", "Check paginated order lists systematically"),
        ("117", "是", "3", "Identify the latest order via sort order"),
        ("126", "是", "3", "Verify page state changes after sort/filter actions"),
        ("143", "是", "3", "Verify pagination before concluding full data coverage"),
    ],
    widths=[2.2, 2.2, 2.6, 9.0],
)
body(
    "进一步统计记忆主题的分布（图 3）可以发现明显的冗余：20 个任务仅产出 9 类主题，其中 4 类重复出现 2—4 次。"
    "原因是任务集中存在大量同模板任务（评论检索类 6 个、订单统计类 5 个），提炼出的经验高度同质。"
    "换言之，记忆库“看起来”有 60 条，实际信息增量仅相当于 9 条。",
)
add_figure("fig3_memory.png", width_cm=14.6)
caption("图 3　记忆主题分布", before=False)

doc.add_heading("4.5　定性观察", level=2)
body(
    "轨迹回放显示，记忆确实进入了决策过程：模型几乎每一步都会显式讨论“Memory Item 1 是否相关”，"
    "并据此调整动作。表 11 给出两个典型案例。",
)
caption("表 11　典型轨迹对比")
add_table(
    ["任务", "实验组表现", "对照组表现", "解读"],
    [
        ("117 首次下单日期", "11 步；每步复述记忆相关性，最终用“每页 50 条”一次性展开全部 37 个订单",
         "5 步；直接翻到第 4 页取最早订单", "记忆建议“去账户订单页”本身是常识，额外讨论只增加开销"),
        ("126 相机价格区间", "20 步；反复校验排序方向与页面状态，多次空转等待",
         "6 步；直接按价格排序并汇报", "记忆中的“先校验页面状态”导致过度自检"),
    ],
    widths=[3.2, 5.4, 3.8, 4.6],
    font_size=8.5,
)

# --------------------------------------------------------------------- 5 讨论
doc.add_heading("5　讨论", level=1)

doc.add_heading("5.1　为何未观察到收益", level=2)
body("结合审计结果与轨迹观察，未观察到成功率收益可从四个层面解释：", indent=True)
bullet("记忆内容过于泛化。提炼出的经验多为“翻完所有分页”“先核对总数”这类模型本就会执行的通用策略，"
       "边际信息量接近于零；真正有价值的是页面上具体的交互陷阱，而这类知识难以从单条轨迹中抽象。")
bullet("任务瓶颈在执行而非策略。失败任务的原因集中于找不到正确元素、模糊题意判断（例如“蛋糕装饰是否算食品”），"
       "属于感知与执行层面，记忆无法直接改善。")
bullet("检索信息量被冗余稀释。由于缺乏按模板去重，注入的 3 条记忆常常是同义重复，相当于只提供了 1 条信息。")
bullet("样本量不足以检出小效应。按配对设计估算，要稳定检出 5 个百分点的差异约需数百个任务；20 个任务的实验中，"
       "单个任务的翻转即可改变结论。")
body(
    "值得注意的是，本轮实验的记忆条件是“最有利”的：记忆库在开跑前已由上一轮同批任务填充，"
    "因此 20 个任务全部注入了 3 条记忆，而非“边跑边积累”（后者第一个任务必然无记忆）。即便如此，成功率仍无差异。",
)

doc.add_heading("5.2　与论文设定的差异", level=2)
caption("表 12　本次复现与论文设定的主要差异")
add_table(
    ["维度", "论文设定", "本次复现", "可能影响"],
    [
        ("任务规模", "shopping 187 个任务，多站点合计 812 个", "20 个任务", "统计功效不足"),
        ("策略模型", "Gemini 2.5 Flash/Pro", "DeepSeek-chat", "指令遵循与网页操作能力差异"),
        ("检索向量", "gemini-embedding-001（3072 维）", "bge-m3（1024 维）", "检索精度与排序差异"),
        ("环境镜像", "官方镜像（45GB，与任务标注完全对齐）", "社区精简镜像（5.4GB）", "页面细节可能不完全一致"),
        ("重复次数", "多次随机种子取平均", "单次", "无法估计方差"),
    ],
    widths=[3.0, 5.6, 4.6, 4.0],
)

doc.add_heading("5.3　方法学教训", level=2)
body(
    "三轮迭代本身构成了本次复现最重要的经验。第一，对照实验必须做“操纵检验”：若实验组的干预未被实际执行，"
    "任何结果差异都只是噪声。第二，环境噪声会伪装成方法效应：页面超时、冷启动、动作超时都会让某一组显著变差，"
    "必须先把基础设施稳定下来再比较算法。第三，跑批顺序会引入系统偏差：先跑的一组承担容器预热成本，"
    "应通过热身任务或交替执行消除。",
)

# --------------------------------------------------------------------- 6 困难
doc.add_heading("6　工程困难与解决", level=1)
body(
    "复现过程中共记录 29 项障碍。按性质分为四类：模型层耦合、依赖与环境、网络与镜像源、运行期缺陷。"
    "这些问题全部属于工程层面，无一源于算法实现本身，这也解释了为何智能体论文的复现往往“跑不起来”而非“跑出来不对”。",
)

caption("表 13　模型层耦合类问题")
add_table(
    ["现象", "根因", "解决"],
    [
        ("导入即报 No API key was provided", "模块顶层执行 vertexai.init()、创建 Gemini 客户端", "改为惰性创建，接入可切换提供者层"),
        ("KeyError: 'deepseek-chat'", "CLIENT_DICT 仅注册三类模型", "增加 get_client() 分发与兼容客户端"),
        ("argparse: invalid choice", "命令行限制模型名白名单", "移除 choices，默认值取环境变量"),
        ("请求被发往 localhost:8000", "未知模型名落入 HuggingFace 分支，base_url 写死", "增加兼容分支并读取配置"),
        ("count_tokens 试图下载 HF 仓库", "把模型名当作 tokenizer 仓库名", "加载失败回退 tiktoken"),
        ("评测阶段报缺少 API key", "评测器模块导入即创建 Gemini 客户端", "改为惰性创建，裁判走兼容接口"),
    ],
    widths=[5.2, 6.0, 6.0],
    font_size=8.5,
)

caption("表 14　依赖与环境类问题")
add_table(
    ["现象", "根因", "解决"],
    [
        ("README 要求的 requirements.txt 不存在", "发布快照遗漏文件", "依 pyproject 重新生成并补齐"),
        ("ModuleNotFoundError: transformers", "代码导入但未在依赖中声明", "补入依赖清单"),
        ("Windows 上 greenlet 编译失败", "Python 3.13 无对应轮子，需 MSVC 编译", "改用 Python 3.12"),
        ("pip 安装时权限错误", "受限环境禁止修改工作区文件权限", "改用 uv 绿色版安装"),
        ("Playwright 无法启动浏览器", "受限环境禁止命名管道", "浏览器操作全部迁至 WSL 内执行"),
        ("playwright install-deps 失败", "Ubuntu 24.04 将 libasound2 改名", "手动安装依赖清单中的 t64 包"),
        ("可编辑安装第三方包失败", "快照缺 README/LICENSE，且构建过程需删除文件", "补齐文件，改用 PYTHONPATH"),
    ],
    widths=[5.2, 5.6, 6.4],
    font_size=8.5,
)

caption("表 15　网络与镜像源类问题")
add_table(
    ["现象", "根因", "解决"],
    [
        ("官方镜像 tar 下载返回 502", "原始分发服务器故障", "改用 Docker Hub 社区镜像"),
        ("archive.org 备份返回 403", "该条目已下架（is_dark）", "同上"),
        ("45GB 镜像下载至 38GB 卡死", "镜像几乎是单个 43GB 层，不支持单层续传", "放弃，改用 5.4GB 精简镜像"),
        ("pull 中途 EOF、解析到异常地址", "关闭代理后 DNS 被污染", "在 Docker Desktop 内配置代理并保持稳定"),
        ("NLTK 数据下载超时", "依赖 raw.githubusercontent.com；新版 NLTK 拒绝代理下载", "用 curl 手动下载至本地目录"),
        ("WSL 无法使用宿主代理", "NAT 模式限制", "以默认网关地址作为代理"),
        ("镜像磁盘只增不减", "虚拟磁盘不会自动收缩", "停止 Docker 后重建数据盘"),
    ],
    widths=[5.2, 5.8, 6.2],
    font_size=8.5,
)

caption("表 16　运行期缺陷类问题")
add_table(
    ["现象", "根因", "解决"],
    [
        ("AssertionError: WA_MAP missing", "环境检查要求 7 个变量全部存在", "补齐占位地址"),
        ("Received an empty action（重试 6 次）", "多行字符串与弯引号破坏动作解析", "系统提示词增加输出格式约束"),
        ("Page.content: page is navigating", "评测器在页面跳转中读取 HTML", "等待加载并重试 5 次"),
        ("Page.goto: Timeout 10000ms", "初始导航超时写死 10 秒，冷启动必崩", "调至 60 秒"),
        ("点击/填表频繁超时、输入被拼接", "动作超时写死 500 毫秒", "调至 3000 毫秒"),
        ("对照组系统性劣于实验组", "跑批顺序导致先跑者承担冷启动", "热身任务或交替执行"),
        ("裁判把漏项判为成功", "LLM 裁判无法核对清单完整性", "对照实验改用官方评测器"),
    ],
    widths=[5.2, 5.8, 6.2],
    font_size=8.5,
)

# --------------------------------------------------------------------- 7 结论
doc.add_heading("7　结论", level=1)
body(
    "本文在非 Google 技术栈、受限网络与单机环境下，完整复现了 ReasoningBank 的记忆机制：智能体在任务结束后提炼结构化经验，"
    "后续任务按意图相似度检索并注入提示词，且在推理过程中被显式引用。迁移工作覆盖策略模型、裁判模型、记忆提炼与检索向量四个层面，"
    "共修改 14 处代码、新增 3 个模块与 7 个脚本。",
)
body(
    "在 20 个购物任务的双组对照中，实验组与对照组的成功率均为 50%，且逐任务判断完全一致；"
    "实验组平均步数由 6.4 升至 8.2，推理开销增加约 28%。结合注入审计与轨迹分析，本文认为：记忆机制本身工作正常，"
    "但在该规模与任务分布下，提炼出的经验过于泛化、冗余度高，无法改善以感知执行为瓶颈的任务表现；"
    "同时，提示词要求的“逐步讨论记忆”带来了可观的额外开销。",
)
body(
    "复现过程中最有价值的发现并非结果本身，而是实验流程中的两次纠错：一次识别出环境噪声伪装成方法效应，"
    "一次通过注入审计发现干预未被真正执行。这说明在智能体类论文的复现中，"
    "建立“干预是否生效”的可验证手段，与实现算法本身同等重要。",
)
body(
    "后续工作可在三个方向推进：扩大任务规模至百级以获得统计功效；引入按模板去重与检索多条记忆以提升信息密度；"
    "以及在相同任务集上复现论文的其他记忆模式（awm、synapse）以做横向比较。",
)

# --------------------------------------------------------------------- 附录
doc.add_page_break()
doc.add_heading("附录 A　关键命令", level=1)
body("以下命令固化于仓库的 scripts/ 目录，可在同类环境中复现整个流程。", indent=True)
add_code([
    "# 1. 环境安装（WSL2 内，Python 3.12 + 依赖 + Chromium + 任务配置）",
    "bash scripts/setup_wsl.sh",
    "",
    "# 2. 拉取精简站点镜像（官方 tar 源已失效）",
    "bash scripts/pull_images.sh shopping",
    "",
    "# 3. 启动站点并修正 Magento 的 base_url",
    "bash scripts/start_shopping.sh",
    "",
    "# 4. 环境体检（12 项，含一次真实 API 调用）",
    "python scripts/doctor.py --net",
    "",
    "# 5. 单任务冒烟",
    "python run.py --task_name webarena.21 --model_name deepseek-chat",
    "",
    "# 6. 对照实验（各 20 个任务）",
    "OUT=./results_mem JUDGE=gt bash ../scripts/run_webarena.sh 0 20 shopping",
    "MEM_MODE=no_memory OUT=./results_nomem JUDGE=gt bash ../scripts/run_webarena.sh 0 20 shopping",
    "",
    "# 7. 结果汇总与注入审计",
    "python ../scripts/report_webarena.py results_mem results_nomem",
    "python ../scripts/audit_memory.py results_mem",
    "",
    "# 8. 轨迹回放（含注入的记忆与每步思考）",
    "python ../scripts/inspect_traj.py results_mem/webarena.126 results_nomem/webarena.126",
])

doc.add_heading("附录 B　数据与脚本清单", level=1)
caption("表 17　仓库新增文件")
add_table(
    ["文件", "用途"],
    [
        ("requirements.txt / requirements-swe.txt", "补齐原仓库缺失的依赖清单"),
        ("WebArena/utils/reasoningbank_llm.py", "模型与向量提供者层"),
        ("scripts/setup_wsl.sh", "一键安装环境"),
        ("scripts/pull_images.sh", "多源回退拉取站点镜像"),
        ("scripts/start_shopping.sh", "启动容器并修正站点地址"),
        ("scripts/doctor.py", "环境体检"),
        ("scripts/smoke_offline.py", "离线自检（不调用 API）"),
        ("scripts/run_webarena.sh", "批量运行封装"),
        ("scripts/report_webarena.py", "成功率与步数汇总、双组对比"),
        ("scripts/audit_memory.py", "记忆注入审计"),
        ("scripts/inspect_traj.py", "轨迹回放"),
        ("scripts/fetch_model.py", "向量模型离线下载"),
        ("report/make_charts.py、build_docx.py", "本报告图表与文档生成脚本"),
    ],
    widths=[7.0, 8.6],
    font_size=8.5,
)

doc.save(str(OUT))

# --------------------------------------------------------------------- 验证
check = Document(str(OUT))
print("段落数:", len(check.paragraphs))
print("表格数:", len(check.tables))
print("图片数:", len(check.inline_shapes))
heads = [(p.style.name, p.text) for p in check.paragraphs if p.style.name.startswith("Heading")]
print("标题数:", len(heads))
actual = [(1 if s == "Heading 1" else 2, t) for s, t in heads]
missing = [h for h in HEADINGS if h not in actual]
extra = [h for h in actual if h not in HEADINGS]
print("目录与正文标题一致:", not missing and not extra, "| 缺:", missing, "| 多:", extra)
print("页码已写入:", sum(1 for h in HEADINGS if h[1] in PAGES), "/", len(HEADINGS))
print("输出:", OUT, OUT.stat().st_size // 1024, "KB")
