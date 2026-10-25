"""用 Pillow 画报告用的三张图（环境里没有 matplotlib）。

输出到 report_assets/：
  fig1_success.png   三轮实验的成功率对比（分组柱状图）
  fig2_steps.png     最终轮两组的步数分布（箱线图 + 散点）
  fig3_memory.png    注入记忆的主题频次（横向条形图）
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "report_assets"
OUT.mkdir(exist_ok=True)

FONT_DIR = Path(r"C:\Windows\Fonts")
FONT = FONT_DIR / "msyh.ttc"
FONT_B = FONT_DIR / "msyhbd.ttc"

C_MEM = (59, 111, 224)
C_NOMEM = (168, 179, 196)
C_GRID = (224, 228, 235)
C_TEXT = (38, 43, 54)
C_MUTED = (120, 128, 140)

# ---------------------------------------------------------------- 数据
ROUNDS = [
    ("第 1 轮", 0.70, 0.60, "含崩溃，无效"),
    ("第 2 轮", 0.60, 0.55, "注入 0/20，无效"),
    ("第 3 轮", 0.50, 0.50, "注入 20/20，有效"),
]

TASKS = ["21", "22", "23", "24", "25", "26", "47", "48", "49", "50",
         "51", "96", "117", "118", "124", "125", "126", "141", "142", "143"]
STEPS_MEM = [4, 5, 3, 2, 3, 3, 6, 3, 6, 6, 8, 3, 4, 3, 30, 18, 30, 7, 12, 8]
STEPS_NOMEM = [7, 4, 4, 2, 5, 3, 3, 7, 4, 4, 4, 3, 4, 3, 24, 23, 4, 6, 9, 5]

THEMES = [
    ("翻完所有评论页再下结论", 4),
    ("系统性地翻查订单分页", 4),
    ("先核对评论总数再扫内容", 3),
    ("排序/筛选后先校验页面状态", 2),
    ("用完整订单列表而非仪表盘", 2),
    ("按排序确定最新订单", 2),
    ("回答前列举所有评论页", 1),
    ("误点后重新校验导航", 1),
    ("下结论前校验分页覆盖", 1),
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_B if bold else FONT), size)


def text_w(draw, s, f):
    return draw.textbbox((0, 0), s, font=f)[2]


def base_canvas(w=1600, h=980, pad=(120, 90, 70, 120)):
    """返回 (img, draw, 绘图区 left/top/right/bottom)。"""
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    left, top, right, bottom = pad
    return img, d, (left, top, w - right, h - bottom)


def draw_axes(d, box, ymax, yticks, ylabel, y_suffix="", grid=True):
    left, top, right, bottom = box
    f_tick = font(26)
    # 网格与刻度
    for i in range(yticks + 1):
        val = ymax * i / yticks
        y = bottom - (bottom - top) * i / yticks
        if grid:
            d.line([(left, y), (right, y)], fill=C_GRID, width=2)
        label = f"{val:.0f}{y_suffix}" if ymax >= 10 else f"{val:.1f}{y_suffix}"
        d.text((left - 18 - text_w(d, label, f_tick), y - 16), label, font=f_tick, fill=C_MUTED)
    # 轴线
    d.line([(left, top), (left, bottom)], fill=(160, 168, 180), width=2)
    d.line([(left, bottom), (right, bottom)], fill=(160, 168, 180), width=2)
    # y 轴标题
    f_lab = font(28)
    d.text((left - 90, top - 55), ylabel, font=f_lab, fill=C_TEXT)


# ---------------------------------------------------------------- 图 1
def fig_success():
    img, d, box = base_canvas()
    left, top, right, bottom = box
    draw_axes(d, box, 1.0, 5, "任务成功率", y_suffix="")

    n = len(ROUNDS)
    slot = (right - left) / n
    bar_w = 92
    gap = 18
    f_val = font(30, bold=True)
    f_x = font(30)
    f_note = font(22)

    for i, (name, mem, nomem, note) in enumerate(ROUNDS):
        cx = left + slot * (i + 0.5)
        for j, (val, color) in enumerate([(mem, C_MEM), (nomem, C_NOMEM)]):
            x0 = cx - bar_w - gap / 2 + j * (bar_w + gap)
            y0 = bottom - (bottom - top) * val
            d.rounded_rectangle([x0, y0, x0 + bar_w, bottom], radius=8, fill=color)
            label = f"{val * 100:.0f}%"
            d.text((x0 + bar_w / 2 - text_w(d, label, f_val) / 2, y0 - 46),
                   label, font=f_val, fill=C_TEXT)
        d.text((cx - text_w(d, name, f_x) / 2, bottom + 22), name, font=f_x, fill=C_TEXT)
        d.text((cx - text_w(d, note, f_note) / 2, bottom + 68), note, font=f_note, fill=C_MUTED)

    # 图例
    lx, ly = left + 20, top + 10
    for color, label in [(C_MEM, "reasoningbank（有记忆）"), (C_NOMEM, "no_memory（对照）")]:
        d.rounded_rectangle([lx, ly, lx + 34, ly + 20], radius=4, fill=color)
        d.text((lx + 48, ly - 6), label, font=font(26), fill=C_TEXT)
        lx += 48 + text_w(d, label, font(26)) + 60

    img.save(OUT / "fig1_success.png")


# ---------------------------------------------------------------- 图 2
def quantile(sorted_vals, q):
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def fig_steps():
    img, d, box = base_canvas()
    left, top, right, bottom = box
    ymax = 32
    draw_axes(d, box, ymax, 4, "每个任务的步数", y_suffix="")

    groups = [("reasoningbank", STEPS_MEM, C_MEM), ("no_memory", STEPS_NOMEM, C_NOMEM)]
    slot = (right - left) / len(groups)
    box_w = 150
    f_lab = font(30)
    f_small = font(25, bold=True)
    f_note = font(22)

    for i, (name, data, color) in enumerate(groups):
        cx = left + slot * (i + 0.5)
        s = sorted(data)
        q1, med, q3 = quantile(s, 0.25), quantile(s, 0.5), quantile(s, 0.75)
        iqr = q3 - q1
        lo = min([v for v in s if v >= q1 - 1.5 * iqr] or [s[0]])
        hi = max([v for v in s if v <= q3 + 1.5 * iqr] or [s[-1]])
        fliers = [v for v in s if v < lo or v > hi]

        def y_of(v):
            return bottom - (bottom - top) * v / ymax

        x0, x1 = cx - box_w / 2, cx + box_w / 2

        # 散点画在最底层，放在箱体右侧的窄带里，避免和箱线重叠
        for k, v in enumerate(data):
            jitter = ((k * 53) % 71) - 35
            px = cx + 150 + jitter
            d.ellipse([px - 6, y_of(v) - 6, px + 6, y_of(v) + 6], fill=(96, 106, 124))

        # 须
        d.line([(cx, y_of(hi)), (cx, y_of(q3))], fill=C_TEXT, width=3)
        d.line([(cx, y_of(q1)), (cx, y_of(lo))], fill=C_TEXT, width=3)
        for v in (hi, lo):
            d.line([(cx - 42, y_of(v)), (cx + 42, y_of(v))], fill=C_TEXT, width=3)
        # 箱体
        d.rectangle([x0, y_of(q3), x1, y_of(q1)], fill=color, outline=C_TEXT, width=3)
        # 中位数
        d.line([(x0, y_of(med)), (x1, y_of(med))], fill="white", width=5)
        # 均值
        mean = sum(s) / len(s)
        my = y_of(mean)
        d.line([(cx - 24, my), (cx + 24, my)], fill=(214, 69, 65), width=5)
        d.line([(cx, my - 11), (cx, my + 11)], fill=(214, 69, 65), width=5)
        label = f"均值 {mean:.1f}"
        d.text((x0 - 26 - text_w(d, label, f_small), my - 15), label, font=f_small, fill=(190, 55, 50))
        # 离群点（超须的，橙色）
        for v in fliers:
            d.ellipse([cx - 9, y_of(v) - 9, cx + 9, y_of(v) + 9], fill=(230, 140, 90))
        d.text((cx - text_w(d, name, f_lab) / 2, bottom + 22), name, font=f_lab, fill=C_TEXT)

    d.text((left, bottom + 78), "灰点为各任务的实际步数；橙色点为超出须的离群值；30 为 max_steps 上限（被截断）",
           font=f_note, fill=C_MUTED)
    img.save(OUT / "fig2_steps.png")


# ---------------------------------------------------------------- 图 3
def fig_memory():
    w, h = 1500, 760
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    left, top, right, bottom = 470, 90, w - 120, h - 70

    data = sorted(THEMES, key=lambda x: x[1])
    n = len(data)
    row = (bottom - top) / n
    bar_h = row * 0.52
    f_lab = font(26)
    f_val = font(28, bold=True)

    maxv = max(v for _, v in data)
    for i, (title, v) in enumerate(data):
        y = bottom - row * (i + 1) + (row - bar_h) / 2
        w_bar = (right - left) * v / maxv
        d.rounded_rectangle([left, y, left + w_bar, y + bar_h], radius=6, fill=C_MEM)
        d.text((left - 24 - text_w(d, title, f_lab), y + bar_h / 2 - 17),
               title, font=f_lab, fill=C_TEXT)
        d.text((left + w_bar + 16, y + bar_h / 2 - 16), str(v), font=f_val, fill=C_TEXT)

    d.line([(left, top - 10), (left, bottom)], fill=(160, 168, 180), width=2)
    d.line([(left, bottom), (right, bottom)], fill=(160, 168, 180), width=2)
    d.text((left - 300, top - 70), "20 个任务提炼出的记忆主题分布（9 类，其中 4 类重复出现）",
           font=font(27), fill=C_TEXT)

    img.save(OUT / "fig3_memory.png")


if __name__ == "__main__":
    fig_success()
    fig_steps()
    fig_memory()
    for p in sorted(OUT.glob("*.png")):
        print(p.name, p.stat().st_size // 1024, "KB")
