"""
gantt_print.py
Vector A3-landscape Gantt printing (WeasyPrint or browser Print -> Save as PDF).

Why this works better than the old print CSS:
  * The chart is drawn as inline SVG (vector: text stays sharp & selectable at any zoom).
  * The SVG is sized in millimetres to EXACTLY fill the A3 printable area (no transform:scale,
    no sticky/overflow tricks that WeasyPrint and browsers ignore when printing).
  * Rows are split across pages automatically (header repeated, stage headers never orphaned),
    all pages share the same scale, so the text size is constant and readable.
"""
import math
import html as _html
import datetime

import numpy as np
import pandas as pd

NP_WEEKMASK = "1111001"          # Sun-Thu working week
PRINT_FONT = "DejaVu Sans, Arial, Helvetica, sans-serif"

# A3 landscape geometry (mm)
PAGE_W, PAGE_H, MARGIN = 420.0, 297.0, 8.0
AVAIL_W = PAGE_W - 2 * MARGIN            # 404
AVAIL_H = PAGE_H - 2 * MARGIN - 14 - 10 - 6   # minus header, legend, safety slack -> 259

STAGE_COLORS = [
    "#2f6fb3", "#e07b39", "#3a9d6b", "#8e5ea2", "#c9a227",
    "#c0504d", "#3b9aa8", "#7a8b3c", "#b5649a", "#6c7a89",
]


def _t(x, y, txt, size=12, weight="normal", fill="#1f2933", anchor="start"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{PRINT_FONT}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{_html.escape(str(txt))}</text>')


def _fit(txt, width_px, size):
    txt = "" if txt is None or (isinstance(txt, float) and np.isnan(txt)) else str(txt)
    n = max(1, int((width_px - 8) / (size * 0.55)))
    return txt if len(txt) <= n else txt[:max(1, n - 1)] + "…"


def _workdays(s, e):
    s, e = pd.Timestamp(s).date(), pd.Timestamp(e).date()
    wd = int(np.busday_count(s, e + datetime.timedelta(days=1), weekmask=NP_WEEKMASK))
    return max(wd, 1) if wd == 0 else wd


def build_gantt_print_html(df, title, today, columns, group_col=None, label_col=None,
                           legend=None, subtitle="", timeline_px=1100):
    """
    df       : needs 'Start Date','End Date' (real dates) and 'Start','End' (dates to plot).
               Optional '_color' (hex) per row.
    columns  : list of (header, width_px, key, align) ; key may be a df column or
               '_s' (start), '_e' (end), '_wd' (working days Sun-Thu).
    group_col: optional column to group rows (e.g. Stage) with summary bars.
    label_col: optional column printed to the right of each bar.
    legend   : optional list of (label, hex_color).
    Returns a standalone HTML string (A3 landscape, one SVG per page).
    """
    ROW_H, HDR_H, FS = 26, 60, 12
    today = pd.Timestamp(today).normalize()
    df = df.copy()
    for c in ("Start", "End", "Start Date", "End Date"):
        df[c] = pd.to_datetime(df[c])

    widths = [c[1] for c in columns]
    LW = sum(widths)
    xs = np.concatenate([[0], np.cumsum(widths)])

    origin = df["Start"].min().normalize() - pd.Timedelta(days=2)
    origin = origin - pd.Timedelta(days=(origin.dayofweek + 1) % 7)      # back to Sunday
    last = df["End"].max().normalize() + pd.Timedelta(days=12)
    n_days = int((last - origin).days)
    n_days += (-n_days) % 7
    days = pd.date_range(origin, periods=n_days, freq="D")
    dw = max(3.0, min(24.0, timeline_px / n_days))
    RW = n_days * dw
    GW = LW + RW

    x_of = lambda ts: (pd.Timestamp(ts).normalize() - origin).days * dw
    w_of = lambda s, e: max(((pd.Timestamp(e).normalize() - pd.Timestamp(s).normalize()).days + 1) * dw, 2.0)
    fmt = lambda v: pd.Timestamp(v).strftime("%d-%b-%Y")

    # ---------------- rows ----------------
    if group_col and group_col in df.columns:
        order = df.groupby(group_col)["Start"].min().sort_values().index.tolist()
        groups = [(g, df[df[group_col] == g].sort_values(["Start", "End"])) for g in order]
    else:
        groups = [(None, df.sort_values(["Start", "End"]))]

    rows = []
    for g, sub in groups:
        if g is not None:
            rows.append({"type": "group", "name": str(g), "sub": sub})
        for _, r in sub.iterrows():
            rows.append({"type": "task", "r": r, "grouped": g is not None})

    # ---------------- pagination (all pages share one scale) ----------------
    aspect = AVAIL_W / AVAIL_H
    rpp = max(10, int((GW / aspect - HDR_H) / ROW_H))
    n_pages = max(1, math.ceil(len(rows) / rpp))
    rpp = math.ceil(len(rows) / n_pages)
    pages, cur = [], []
    for row in rows:
        if len(cur) >= rpp:
            carry = []
            while cur and cur[-1]["type"] == "group":      # never leave a stage header alone at page end
                carry.insert(0, cur.pop())
            pages.append(cur)
            cur = carry
        cur.append(row)
    if cur:
        pages.append(cur)

    max_rows = max(len(p) for p in pages)
    H_ref = HDR_H + max_rows * ROW_H
    w_mm = AVAIL_W
    h_mm = w_mm * H_ref / GW
    if h_mm > AVAIL_H:                                       # safety: shrink uniformly
        h_mm = AVAIL_H
        w_mm = h_mm * GW / H_ref
    mm_per_px = w_mm / GW

    # ---------------- cell text ----------------
    def cell(key, r=None, sub=None):
        if key == "_s":
            return fmt(r["Start Date"] if r is not None else sub["Start Date"].min())
        if key == "_e":
            return fmt(r["End Date"] if r is not None else sub["End Date"].max())
        if key == "_wd":
            if r is not None:
                return str(_workdays(r["Start Date"], r["End Date"]))
            return str(_workdays(sub["Start Date"].min(), sub["End Date"].max()))
        if r is None:
            return ""
        v = r.get(key, "")
        return "" if pd.isnull(v) else str(v)

    # ---------------- one page SVG ----------------
    def page_svg(page_rows):
        n = len(page_rows)
        H = HDR_H + n * ROW_H
        o = []
        o.append(f'<rect x="0" y="0" width="{GW:.1f}" height="{H}" fill="#ffffff"/>')

        # header background
        o.append(f'<rect x="0" y="0" width="{GW:.1f}" height="{HDR_H}" fill="#eef1f5"/>')
        for k, (hd, w, _, al) in enumerate(columns):
            tx = xs[k] + (w - 6 if al == "end" else 6)
            o.append(_t(tx, HDR_H - 9, _fit(hd, w, FS), FS, "bold", "#374151", "end" if al == "end" else "start"))
            if k:
                o.append(f'<line x1="{xs[k]}" y1="{HDR_H - 24}" x2="{xs[k]}" y2="{HDR_H}" stroke="#d3d8df"/>')

        # timeline header: months / weeks / days
        i = 0
        while i < n_days:
            j = i
            while j < n_days and days[j].month == days[i].month:
                j += 1
            wpx = (j - i) * dw
            label = f"{days[i]:%B %Y}" if wpx >= 90 else f"{days[i]:%b %y}"
            o.append(f'<rect x="{LW + i * dw:.1f}" y="0" width="{wpx:.1f}" height="20" fill="#eef1f5" stroke="#d3d8df"/>')
            o.append(_t(LW + i * dw + 5, 14, _fit(label, wpx, 11), 11, "bold", "#374151"))
            i = j
        for w in range(0, n_days, 7):
            o.append(f'<rect x="{LW + w * dw:.1f}" y="20" width="{7 * dw:.1f}" height="20" fill="#eef1f5" stroke="#d3d8df"/>')
            o.append(_t(LW + w * dw + 4, 34, f"{days[w]:%d %b}", 10, "normal", "#374151"))
        for k, d in enumerate(days):
            wk = d.dayofweek in (4, 5)
            o.append(f'<rect x="{LW + k * dw:.1f}" y="40" width="{dw:.2f}" height="20" '
                     f'fill="{"#d9dde3" if wk else "#eef1f5"}" stroke="#d3d8df" stroke-width="0.5"/>')
            if dw >= 10:
                o.append(_t(LW + k * dw + dw / 2, 54, d.day, 8, "normal", "#52606d", "middle"))
        o.append(f'<line x1="0" y1="{HDR_H}" x2="{GW:.1f}" y2="{HDR_H}" stroke="#9aa4b2"/>')

        # weekend shading + week lines in body
        for k, d in enumerate(days):
            if d.dayofweek in (4, 5):
                o.append(f'<rect x="{LW + k * dw:.1f}" y="{HDR_H}" width="{dw:.2f}" height="{n * ROW_H}" '
                         f'fill="#8c96a5" fill-opacity="0.15"/>')
        for w in range(0, n_days + 1, 7):
            o.append(f'<line x1="{LW + w * dw:.1f}" y1="{HDR_H}" x2="{LW + w * dw:.1f}" y2="{H}" stroke="#cfd5dd" stroke-width="0.7"/>')

        # rows
        for idx, row in enumerate(page_rows):
            y0 = HDR_H + idx * ROW_H
            ty = y0 + ROW_H / 2 + FS * 0.35
            if row["type"] == "group":
                sub = row["sub"]
                col = sub["_color"].iloc[0] if "_color" in sub.columns else STAGE_COLORS[0]
                o.append(f'<rect x="0" y="{y0}" width="{LW}" height="{ROW_H}" fill="#e8edf3"/>')
                for k, (hd, w, key, al) in enumerate(columns):
                    if k == 1 or (len(columns) == 1):
                        o.append(f'<rect x="{xs[k] + 6}" y="{y0 + 8}" width="10" height="10" rx="2" fill="{col}"/>')
                        o.append(_t(xs[k] + 22, ty, _fit(row["name"], w - 16, FS), FS, "bold"))
                    elif key in ("_s", "_e", "_wd"):
                        txt = cell(key, None, sub)
                        o.append(_t(xs[k] + (w - 6 if al == "end" else 6), ty, _fit(txt, w, FS), FS, "bold",
                                    anchor="end" if al == "end" else "start"))
                ps, pe = sub["Start"].min(), sub["End"].max()
                bx, bw = LW + x_of(ps), w_of(ps, pe)
                o.append(f'<rect x="{bx:.1f}" y="{y0 + 7}" width="{bw:.1f}" height="5" fill="#1f2933"/>')
                for px in (bx, bx + bw):
                    o.append(f'<polygon points="{px - 4.5:.1f},{y0 + 12} {px + 4.5:.1f},{y0 + 12} {px:.1f},{y0 + 18}" fill="#1f2933"/>')
            else:
                r = row["r"]
                col = r["_color"] if "_color" in r.index and pd.notnull(r["_color"]) else STAGE_COLORS[0]
                for k, (hd, w, key, al) in enumerate(columns):
                    txt = _fit(cell(key, r), w - (8 if (k == 1 and row["grouped"]) else 0), FS)
                    tx = xs[k] + (w - 6 if al == "end" else (14 if (k == 1 and row["grouped"]) else 6))
                    o.append(_t(tx, ty, txt, FS, "normal", "#1f2933", "end" if al == "end" else "start"))
                bx, bw = LW + x_of(r["Start"]), w_of(r["Start"], r["End"])
                o.append(f'<rect x="{bx:.1f}" y="{y0 + 6}" width="{bw:.1f}" height="14" rx="2" fill="{col}"/>')
                o.append(f'<rect x="{bx:.1f}" y="{y0 + 18}" width="{bw:.1f}" height="2" fill="#000000" fill-opacity="0.18"/>')
                if label_col and label_col in r.index and pd.notnull(r[label_col]) and str(r[label_col]).strip():
                    lab = _fit(r[label_col], 160, 10.5)
                    est = len(lab) * 10.5 * 0.58
                    if bx + bw + 5 + est > GW - 4:
                        o.append(_t(bx - 5, ty, lab, 10.5, "normal", "#52606d", "end"))
                    else:
                        o.append(_t(bx + bw + 5, ty, lab, 10.5, "normal", "#52606d"))
            o.append(f'<line x1="0" y1="{y0 + ROW_H}" x2="{GW:.1f}" y2="{y0 + ROW_H}" stroke="#e3e7ec"/>')

        # column separators + frame
        for k in range(1, len(columns)):
            o.append(f'<line x1="{xs[k]}" y1="{HDR_H}" x2="{xs[k]}" y2="{H}" stroke="#eef0f3"/>')
        o.append(f'<line x1="{LW}" y1="0" x2="{LW}" y2="{H}" stroke="#9aa4b2" stroke-width="2"/>')
        if origin <= today < last:
            tx = LW + x_of(today) + dw / 2
            o.append(f'<line x1="{tx:.1f}" y1="{HDR_H}" x2="{tx:.1f}" y2="{H}" stroke="#e03131" '
                     f'stroke-width="1.6" stroke-dasharray="6,4"/>')
        o.append(f'<rect x="0.5" y="0.5" width="{GW - 1:.1f}" height="{H - 1}" fill="none" stroke="#9aa4b2"/>')

        hh = H * mm_per_px
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w_mm:.2f}mm" height="{hh:.2f}mm" '
                f'viewBox="0 0 {GW:.1f} {H}" style="width:{w_mm:.2f}mm;height:{hh:.2f}mm;display:block">'
                + "".join(o) + "</svg>")

    # ---------------- legend ----------------
    legend_html = ""
    if legend:
        legend_html = "".join(
            f'<span style="display:inline-block;margin-right:14px;font-size:9pt;color:#334155;">'
            f'<span style="display:inline-block;width:10px;height:10px;background:{c};margin-right:4px;"></span>'
            f'{_html.escape(str(l))}</span>' for l, c in legend)
    legend_html += ('<span style="font-size:9pt;color:#334155;margin-right:14px;">'
                    '<span style="display:inline-block;width:0;height:10px;border-left:2px dashed #e03131;margin-right:4px;"></span>Today</span>'
                    '<span style="font-size:9pt;color:#334155;">'
                    '<span style="display:inline-block;width:10px;height:10px;background:#d9dde3;margin-right:4px;"></span>Weekend (Fri-Sat)</span>')

    # ---------------- document ----------------
    page_divs = []
    for pi, pr in enumerate(pages, 1):
        page_divs.append(f"""
<div class="page">
  <div class="hdr">
    <div><div class="ttl">{_html.escape(title)}</div>
         <div class="meta">{_html.escape(subtitle)} &nbsp;|&nbsp; Generated: {today:%d-%b-%Y} &nbsp;|&nbsp; A3 Landscape</div></div>
    <div class="meta" style="text-align:right">Page {pi} / {len(pages)}</div>
  </div>
  {page_svg(pr)}
  <div class="leg">{legend_html}</div>
</div>""")

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{_html.escape(title)}</title>
<style>
@page {{ size: A3 landscape; margin: {MARGIN}mm; }}
*{{box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
html,body{{margin:0;padding:0;background:#fff;font-family:{PRINT_FONT}}}
.page{{width:{AVAIL_W}mm;page-break-after:always;break-after:page}}
.page:last-child{{page-break-after:auto;break-after:auto}}
.hdr{{display:flex;justify-content:space-between;align-items:flex-end;height:12mm;margin-bottom:2mm;
     border-bottom:0.6mm solid #2f6fb3;padding-bottom:1mm}}
.ttl{{font-size:16pt;font-weight:bold;color:#1e3a8a}}
.meta{{font-size:9pt;color:#64748b}}
.leg{{margin-top:2mm;height:6mm;line-height:6mm}}
.noprint{{display:none}}
@media screen{{
  body{{background:#e5e7eb;padding:12px}}
  .page{{background:#fff;margin:0 auto 14px;padding:{MARGIN}mm;width:{PAGE_W}mm;box-shadow:0 1px 6px rgba(0,0,0,.25)}}
  .noprint{{display:block;margin:0 auto 10px;width:{PAGE_W}mm;text-align:right}}
}}
</style></head>
<body>
<div class="noprint"><button onclick="window.print()" style="background:#2563eb;color:#fff;border:0;padding:7px 16px;border-radius:4px;font-weight:600;cursor:pointer">
Print / Save as A3 PDF (Layout: Landscape, Margins: Default, Background graphics: ON)</button></div>
{''.join(page_divs)}
</body></html>"""


# ----------------------------------------------------------------------
# Ready-made wrappers
# ----------------------------------------------------------------------
def build_wbs_print(df, today):
    """df = the prepared WBS dataframe from render_wbs_gantt (needs Code, Stage, Disc, Resp, Start, End ...)."""
    df = df.copy()
    stage_order = df.groupby("Stage")["Start"].min().sort_values().index.tolist()
    color_of = {s: STAGE_COLORS[i % len(STAGE_COLORS)] for i, s in enumerate(stage_order)}
    df["_color"] = df["Stage"].map(color_of)
    if "TaskTxt" not in df.columns:
        df["TaskTxt"] = df["Task"]
    cols = [("WBS", 52, "Code", "start"), ("Task Name", 250, "TaskTxt", "start"),
            ("Start", 94, "_s", "start"), ("End", 94, "_e", "start"),
            ("Days", 40, "_wd", "end"), ("Dept", 90, "Disc", "start")]
    return build_gantt_print_html(
        df, "Project Schedule & WBS Gantt Chart", today, cols,
        group_col="Stage", label_col="Resp", legend=list(color_of.items()),
        subtitle=f"Total tasks: {len(df)}")


def build_team_print(calc_df, team_name, disciplines, name_col, label_fn, hide_completed=False):
    """label_fn(row, name_col) -> project label (use make_project_label)."""
    today = pd.Timestamp.today().normalize()
    df = calc_df.copy()
    df["Start Date"] = pd.to_datetime(df["Start Date"], errors="coerce")
    df["End Date"] = pd.to_datetime(df["End Date"], errors="coerce")
    df["End Date"] = df["End Date"].fillna(df["Start Date"])
    df["Start Date"] = df["Start Date"].fillna(df["End Date"])
    df = df.dropna(subset=["Start Date", "End Date"])
    df = df[df["End Date"] >= df["Start Date"]]
    if hide_completed:
        df = df[df["End Date"] >= today]
    if df.empty:
        return None
    df["Start"], df["End"] = df["Start Date"], df["End Date"]
    df["Project"] = df.apply(lambda r: label_fn(r, name_col), axis=1)
    hrs_cols = [f"{d} (Hrs)" for d in disciplines if f"{d} (Hrs)" in df.columns]
    df["Hours"] = (df[hrs_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1).round(0).astype(int).astype(str)
                   if hrs_cols else "")
    done = df["End Date"] < today
    df["Status"] = np.where(done, "Completed", "Active")
    df["_color"] = np.where(done, "#94a3b8", "#2563eb")
    cols = [("Project", 270, "Project", "start"), ("Start", 94, "_s", "start"), ("End", 94, "_e", "start"),
            ("Days", 40, "_wd", "end"), ("Hrs", 56, "Hours", "end"), ("Status", 76, "Status", "start")]
    return build_gantt_print_html(
        df, f"{team_name} - Project Timeline", today, cols,
        legend=[("Active / Upcoming", "#2563eb"), ("Completed", "#94a3b8")],
        subtitle=f"Total projects: {len(df)}", timeline_px=1000)
