"""توليد الرسوم البيانية ومنحنيات التقارب (Iteration -> Best Fitness) للتجارب."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, Normalize  # noqa: E402
from matplotlib.patches import Circle, Rectangle, Patch  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

from .scenarios import ROOT, load_config, load_scenario  # noqa: E402
from .experiments import city_path  # noqa: E402
from .stats import COLORS, ORDER, SIZES, UNSAFE  # noqa: E402

SURFACE = "#fcfcfb"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
FIRE, GROUND_FIRE = "#d03b3b", "#ec835a"
DRONES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]   # ترتيب فئات ثابت
TOWERS = LinearSegmentedColormap.from_list("towers", ["#dedcd4", "#3a3937"])   # لون محايد واحد، من الفاتح إلى الداكن

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": "#c3c2b7",
    "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
})

MARKERS = {"GA": "o", "PSO": "s", "ACO": "^", "DP": "D"}
SPINE = "#c3c2b7"


def _style(ax, grid_axis="both"):
    ax.set_facecolor(SURFACE)
    ax.grid(axis=grid_axis, color=GRID, lw=0.6, which="major")
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=8.5)
    for s in ax.spines.values():
        s.set_color(SPINE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def _save(fig, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140, facecolor=SURFACE)
    plt.close(fig)


def _title(fig, text, sub=None) -> float:
    """العنوان (والعنوان الفرعي) على مسافات ثابتة من الأعلى؛ تعيد أعلى المساحة الحرة لـ tight_layout."""
    h = fig.get_figheight()
    fig.text(0.01, 1 - 0.16 / h, text, ha="left", va="top", fontsize=12.5, color=INK)
    if sub:
        fig.text(0.01, 1 - 0.46 / h, sub, ha="left", va="top", fontsize=9.5, color=INK2)
    return 1 - (0.85 if sub else 0.55) / h


def _plain(axis):
    """أرقام عادية على محور لوغاريتمي (0.1 و1 و10 و100 بدل 10^-1 ...)."""
    from matplotlib.ticker import FuncFormatter
    axis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    axis.set_minor_formatter(FuncFormatter(lambda v, _: ""))


def _sizes(df):
    return [s for s in SIZES if s in set(df["size"])]


# معاينات المدن
def _top(ax, scn, norm, labels=True, legend=True, straight=True, goal_color=None):
    W, d = scn.W, scn.world["d_safe"]
    ax.set_xlim(0, W)
    ax.set_ylim(0, W)
    ax.set_aspect("equal")
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for b in scn.buildings:
        ax.add_patch(Rectangle((b.x0 - d, b.y0 - d), b.x1 - b.x0 + 2 * d, b.y1 - b.y0 + 2 * d,
                               fill=False, ls=(0, (2, 2)), lw=0.6, ec=MUTED, zorder=2))
        ax.add_patch(Rectangle((b.x0, b.y0), b.x1 - b.x0, b.y1 - b.y0, fc=TOWERS(norm(b.h)),
                               ec=SURFACE, lw=0.8, zorder=3))
    for m in scn.missions:
        col = goal_color or DRONES[m.k % len(DRONES)]
        if straight:
            ax.plot([m.S[0], m.G[0]], [m.S[1], m.G[1]], ls=(0, (4, 3)), lw=1.4, color=col, zorder=4)
        ax.scatter(*m.G[:2], marker="X", s=70, color=col, ec=SURFACE, lw=1.2, zorder=6)
        if labels:
            ax.annotate(f"D{m.k + 1}", m.G[:2], xytext=(6, 6), textcoords="offset points",
                        color=INK, fontsize=8, fontweight="bold", zorder=7)
    for f in scn.fires:
        col = FIRE if f.handled_by == "drone" else GROUND_FIRE
        ax.add_patch(Circle(f.c[:2], f.R, fc=col, alpha=0.18, ec=col, lw=0.8, zorder=4))
        ax.scatter(*f.c[:2], marker="*", s=120, color=col, ec=SURFACE, lw=0.8, zorder=6)
    S = np.array(scn.staging["points"])
    ax.scatter(S[:, 0], S[:, 1], marker="^", s=55, color=INK, ec=SURFACE, lw=1.0, zorder=6)
    if legend:
        h = [plt.Line2D([], [], marker="^", ls="", color=INK, label="take-off point"),
             plt.Line2D([], [], marker="*", ls="", ms=10, color=FIRE, label="fire (drone mission)"),
             plt.Line2D([], [], marker="X", ls="", color=INK2, label="capsule release point"),
             plt.Line2D([], [], ls=(0, (4, 3)), color=INK2, label="straight line (not a planned path)"),
             Rectangle((0, 0), 1, 1, fill=False, ls=(0, (2, 2)), ec=MUTED, label="5 m safety margin")]
        if any(f.handled_by == "ground" for f in scn.fires):
            h.insert(2, plt.Line2D([], [], marker="*", ls="", ms=10, color=GROUND_FIRE,
                                   label="low fire (ground crews)"))
        ax.legend(handles=h, loc="upper left", bbox_to_anchor=(0, -0.08), ncol=2, frameon=False,
                  fontsize=8, labelcolor=INK2)
    ax.set_xlabel("x (m, east)")
    ax.set_ylabel("y (m, north)")


def _box_faces(x0, y0, x1, y1, h):
    p = np.array([[x0, y0, 0], [x1, y0, 0], [x1, y1, 0], [x0, y1, 0],
                  [x0, y0, h], [x1, y0, h], [x1, y1, h], [x0, y1, h]])
    return [p[[0, 1, 5, 4]], p[[1, 2, 6, 5]], p[[2, 3, 7, 6]], p[[3, 0, 4, 7]], p[[4, 5, 6, 7]]]


def _three_d(ax, scn, norm):
    W, zmax = scn.W, scn.world["z_max"]
    light = np.array([0.35, -0.6, 0.72])
    light /= np.linalg.norm(light)
    faces, colors = [], []
    for b in scn.buildings:
        base = np.array(matplotlib.colors.to_rgb(TOWERS(norm(b.h))))
        for face, n in zip(_box_faces(b.x0, b.y0, b.x1, b.y1, b.h),
                           [(0, -1, 0), (1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, 0, 1)]):
            faces.append(face)
            colors.append(np.clip(base * (0.65 + 0.35 * max(np.dot(n, light), 0)), 0, 1))
    # مجموعة واحدة، ليرتب matplotlib كل وجه بحسب العمق
    ax.add_collection3d(Poly3DCollection(faces, facecolors=colors, edgecolors=(1, 1, 1, 0.35),
                                         linewidths=0.3, zsort="max"))
    for m in scn.missions:
        col = DRONES[m.k % len(DRONES)]
        ax.plot([m.S[0], m.G[0]], [m.S[1], m.G[1]], [m.S[2], m.G[2]], ls=(0, (4, 3)), lw=1.2, color=col)
        ax.scatter(*m.G, marker="X", s=40, color=col, depthshade=False)
    for f in scn.fires:
        col = FIRE if f.handled_by == "drone" else GROUND_FIRE
        ax.scatter(*f.c, marker="*", s=110, color=col, depthshade=False, ec=SURFACE, lw=0.5)
    S = np.array(scn.staging["points"])
    ax.scatter(S[:, 0], S[:, 1], S[:, 2], marker="^", s=30, color=INK, depthshade=False)
    ax.set_xlim(0, W)
    ax.set_ylim(0, W)
    ax.set_zlim(0, zmax)
    ax.set_box_aspect((1, 1, max(zmax / W, 0.35)))
    ax.view_init(elev=28, azim=-58)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_zlabel("z (m)")
    for a in (ax.xaxis, ax.yaxis, ax.zaxis):
        a.pane.set_facecolor(SURFACE)
        a.pane.set_edgecolor(GRID)
        a._axinfo["grid"]["color"] = GRID


def preview_city(path, out):
    cfg = load_config()
    scn = load_scenario(path)
    s = cfg["sizes"][scn.size]
    norm = Normalize(*s["height"])
    fig = plt.figure(figsize=(13, 6.6))
    ax1 = fig.add_axes([0.05, 0.22, 0.40, 0.66])
    ax2 = fig.add_axes([0.47, 0.12, 0.50, 0.82], projection="3d")
    _top(ax1, scn, norm)
    _three_d(ax2, scn, norm)
    cax = fig.add_axes([0.60, 0.085, 0.25, 0.018])
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=TOWERS), cax=cax, orientation="horizontal")
    cb.set_label("tower height (m)", color=INK2)
    cb.outline.set_visible(False)
    w = scn.world
    fig.text(0.05, 0.955, f"{scn.size.capitalize()} city  ·  {w['W']} × {w['W']} × {w['z_max']} m",
             fontsize=14, fontweight="bold", color=INK)
    fig.text(0.05, 0.915, f"{len(scn.buildings)} towers, {len(scn.fires)} fire(s), {len(scn.missions)} drone(s)"
             f"  ·  seed {scn.seed_used}  ·  file: {Path(path).relative_to(ROOT)}", fontsize=9.5, color=INK2)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)


def preview_random(size, out):
    cfg = load_config()
    norm = Normalize(*cfg["sizes"][size]["height"])
    files = sorted((ROOT / "scenarios" / "random").glob(f"{size}_r*.json"))
    fig, axs = plt.subplots(2, 5, figsize=(16, 7.2))
    for ax, p in zip(axs.ravel(), files):
        scn = load_scenario(p)
        _top(ax, scn, norm, labels=False, legend=False)
        ax.set_title(p.stem, fontsize=9, color=INK2)
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.tick_params(labelsize=7)
    fig.suptitle(f"10 random {size} cities (top view): towers grey by height, ★ fire, ✕ release point, ▲ take-off",
                 fontsize=12, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110)
    plt.close(fig)


HEAT = LinearSegmentedColormap.from_list("heat", [SURFACE, "#f6c9a8", "#e8743b", "#b8361a", "#6e1a0c"])


def preview_hazard(path, out, fire_index=0):
    """حقل الخطر حول حريق واحد: مقطع رأسي على العمود الخارجي للواجهة + منظر علوي عند ارتفاع الحريق."""
    from .geometry import FireField

    scn = load_scenario(path)
    field = FireField.from_scenario(scn)
    f = scn.fires[fire_index]
    c, n = np.array(f.c), np.array(f.normal[:2])
    zmax, d = scn.world["z_max"], scn.world["d_safe"]
    levels = np.linspace(0, 1, 21)

    fig = plt.figure(figsize=(13, 5.8))
    ax1 = fig.add_axes([0.06, 0.14, 0.44, 0.70])
    ax2 = fig.add_axes([0.56, 0.14, 0.30, 0.70])
    cax = fig.add_axes([0.89, 0.24, 0.012, 0.50])

    # المقطع الرأسي: u = المسافة الأفقية عن الواجهة (للخارج)، وz = الارتفاع
    u = np.linspace(-60, 120, 361)
    z = np.linspace(0, zmax, int(zmax * 2) + 1)
    U, Z = np.meshgrid(u, z)
    P = np.stack([c[0] + U * n[0], c[1] + U * n[1], Z], axis=-1)
    Hs = field.H(P.reshape(-1, 3)).reshape(U.shape)
    cf = ax1.contourf(U, Z, Hs, levels=levels, cmap=HEAT, vmin=0, vmax=1)
    ax1.contour(U, Z, Hs, levels=[0.1], colors=[MUTED], linewidths=0.8, linestyles="dashed")
    ax1.contour(U, Z, Hs, levels=[field.tau_core], colors=[FIRE], linewidths=2.0)
    for b in scn.buildings:      # الأبراج التي يقطعها خط المقطع
        ts = []
        for k in range(2):
            if abs(n[k]) > 1e-9:
                lo, hi = (np.array([b.x0, b.y0])[k] - c[k]) / n[k], (np.array([b.x1, b.y1])[k] - c[k]) / n[k]
                ts.append((min(lo, hi), max(lo, hi)))
            else:
                inside = [b.x0, b.y0][k] <= c[k] <= [b.x1, b.y1][k]
                ts.append((-np.inf, np.inf) if inside else (np.inf, -np.inf))
        a0, a1 = max(ts[0][0], ts[1][0]), min(ts[0][1], ts[1][1])
        if a0 < a1:
            ax1.add_patch(Rectangle((a0 - d, 0), a1 - a0 + 2 * d, b.h + d, fill=False, ls=(0, (2, 2)),
                                    ec=INK2, lw=0.8, zorder=3))
            ax1.add_patch(Rectangle((a0, 0), a1 - a0, b.h, fc="#8f8d86", ec=SURFACE, lw=0.8, zorder=4))
    ax1.scatter([0], [c[2]], marker="*", s=180, color=FIRE, ec=SURFACE, lw=0.8, zorder=6)
    m = next((m for m in scn.missions if m.fire == f.id), None)
    if m is not None:
        ax1.scatter([1.6 * f.R], [m.G[2]], marker="X", s=80, color=DRONES[m.k % 5], ec=SURFACE, lw=1, zorder=6)
        ax1.annotate("release point", (1.6 * f.R, m.G[2]), xytext=(8, -12), textcoords="offset points",
                     color=INK, fontsize=8.5)
    ax1.annotate("no-fly core (H ≥ 0.5)", (field.core_radius_at_fire_height(fire_index) * 0.6,
                                         c[2] + field.core_top_above_fire(fire_index) * 0.75),
                 xytext=(40, 30), textcoords="offset points", color=INK, fontsize=8.5,
                 arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax1.set_xlim(u[0], u[-1])
    ax1.set_ylim(0, zmax)
    ax1.set_xlabel("distance from the burning facade (m, outwards)")
    ax1.set_ylabel("height z (m)")
    ax1.set_title("Vertical section through the fire", loc="left", fontsize=10.5, color=INK)

    # منظر علوي عند ارتفاع الحريق
    span = 110
    xs = np.linspace(c[0] - span, c[0] + span, 221)
    ys = np.linspace(c[1] - span, c[1] + span, 221)
    X, Y = np.meshgrid(xs, ys)
    Ht = field.H(np.stack([X, Y, np.full_like(X, c[2])], axis=-1).reshape(-1, 3)).reshape(X.shape)
    ax2.contourf(X, Y, Ht, levels=levels, cmap=HEAT, vmin=0, vmax=1)
    ax2.contour(X, Y, Ht, levels=[0.1], colors=[MUTED], linewidths=0.8, linestyles="dashed")
    ax2.contour(X, Y, Ht, levels=[field.tau_core], colors=[FIRE], linewidths=2.0)
    for b in scn.buildings:
        if b.h >= c[2]:
            ax2.add_patch(Rectangle((b.x0, b.y0), b.x1 - b.x0, b.y1 - b.y0, fc="#8f8d86", ec=SURFACE, lw=0.8))
    ax2.scatter(*c[:2], marker="*", s=160, color=FIRE, ec=SURFACE, lw=0.8, zorder=6)
    if m is not None:
        ax2.scatter(*m.G[:2], marker="X", s=70, color=DRONES[m.k % 5], ec=SURFACE, lw=1, zorder=6)
    ax2.set_xlim(xs[0], xs[-1])
    ax2.set_ylim(ys[0], ys[-1])
    ax2.set_aspect("equal")
    ax2.set_xlabel("x (m)")
    ax2.set_ylabel("y (m)")
    ax2.set_title(f"Top view at the fire height (z = {c[2]:.0f} m)", loc="left", fontsize=10.5, color=INK)

    cb = fig.colorbar(cf, cax=cax, ticks=[0, 0.1, 0.25, 0.5, 0.75, 1])
    cb.set_label("hazard H", color=INK2)
    cb.outline.set_visible(False)
    fig.text(0.06, 0.94, f"Fire hazard field  ·  {scn.size} city, fire {f.id}", fontsize=14,
             fontweight="bold", color=INK)
    fig.text(0.06, 0.895, f"R = {f.R} m, I = {f.I}, Hf = {f.Hf:.0f} m, k = {field.k}  ·  red line: no-fly core, "
             f"dashed: H = 0.1  ·  grey: towers (dotted: 5 m margin)", fontsize=9.5, color=INK2)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    plt.close(fig)


# التقارب
def convergence(main, curves, out):
    sizes = _sizes(main)
    fig, axs = plt.subplots(2, len(sizes), figsize=(5.2 * len(sizes), 8.2), squeeze=False)
    for j, size in enumerate(sizes):
        dp = main[(main["size"] == size) & (main["algorithm"] == "DP")]["F"]
        safe_hi, safe_lo, med_max = [], [], []
        for row, ax in enumerate(axs[:, j]):
            _style(ax)
            for alg in ["GA", "PSO", "ACO"]:
                cs = [c for (part, a, city, seed), c in curves.items()
                      if part == "main" and a == alg and city == size]
                if not cs:
                    continue
                n = min(len(c) for c in cs)
                Y = np.array([[b for _, _, b in c[:n]] for c in cs])
                it = np.array([i for i, _, _ in cs[0][:n]])
                med, q1, q3 = np.median(Y, 0), np.percentile(Y, 25, 0), np.percentile(Y, 75, 0)
                ax.fill_between(it, q1, q3, color=COLORS[alg], alpha=0.16, lw=0)
                final = np.median([c[-1][2] for c in cs])            # آخر قيمة لكل تشغيل
                ax.plot(it, med, color=COLORS[alg], lw=2, label=f"{alg}  (final median {final:.3f})")
                if row == 0:
                    med_max.append(med.max())
                    safe = med[med < UNSAFE]
                    if len(safe):
                        safe_hi.append(np.percentile(safe, 80))
                    safe_lo.append(Y.min())
            if len(dp):
                ax.axhline(dp.iloc[0], color=COLORS["DP"], ls=(0, (5, 3)), lw=1.6,
                           label=f"DP (exact on the grid, one search)  {dp.iloc[0]:.3f}")
            ax.set_xlabel("iteration (generation / swarm step / ant colony cycle)", color=INK2, fontsize=9)
        top, bottom = axs[0, j], axs[1, j]
        if med_max and max(med_max) > 10 * min(safe_lo):
            top.set_yscale("log")                                # خطط غير آمنة (F > 100) في البداية
            _plain(top.yaxis)
            top.set_ylabel("best F so far (log scale)", color=INK2)
        else:
            top.set_ylabel("best F so far", color=INK2)
        top.set_title(f"{size} city: whole run", loc="left", fontsize=10.5, color=INK)
        top.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper right")
        extra = [dp.iloc[0]] if len(dp) else []
        lo = min(safe_lo + extra) if safe_lo + extra else 1.0
        hi = max(safe_hi + extra) if safe_hi + extra else UNSAFE
        bottom.set_ylim(lo - 0.03 * (hi - lo), hi + 0.05 * (hi - lo))
        bottom.set_ylabel("best F so far (safe plans only)", color=INK2)
        bottom.set_title(f"{size} city: zoom on the safe plans", loc="left", fontsize=10.5, color=INK)
    top_ = _title(fig, "Iteration → Best Fitness on the three main cities (lower is better)",
           "Line = median over the seeds, band = middle 50 %. F > 100: the plan still breaks a rule. Same budget and population "
           "size for all three, so an iteration costs about the same (GA keeps 2 elite plans: a few more generations).")
    fig.tight_layout(rect=(0, 0, 1, top_))
    _save(fig, out / "convergence.png")


# توزيع النتائج
def distribution(main, out):
    sizes = _sizes(main)
    fig, axs = plt.subplots(1, len(sizes), figsize=(5.0 * len(sizes), 4.8), squeeze=False)
    rng = np.random.default_rng(0)
    for ax, size in zip(axs[0], sizes):
        _style(ax, "y")
        d = main[main["size"] == size]
        algs = [a for a in ORDER if a in set(d["algorithm"])]
        hidden = []
        for i, alg in enumerate(algs):
            F = d[d["algorithm"] == alg]["F"].values
            hidden += [f"{alg} F = {f:.1f}" for f in F[F >= UNSAFE]]
            F = F[F < UNSAFE]
            if not len(F):
                continue
            if len(F) > 1:
                ax.boxplot([F], positions=[i], widths=0.5, showfliers=False, patch_artist=True,
                           medianprops={"color": INK, "lw": 1.6},
                           boxprops={"facecolor": COLORS[alg], "alpha": 0.18, "edgecolor": COLORS[alg]},
                           whiskerprops={"color": COLORS[alg]}, capprops={"color": COLORS[alg]})
            x = i + rng.uniform(-0.16, 0.16, len(F)) if len(F) > 1 else np.array([i])
            ax.scatter(x, F, s=26 if len(F) > 1 else 70, marker=MARKERS[alg], color=COLORS[alg],
                       ec=SURFACE, lw=0.8, zorder=3, label=f"{alg} ({len(F)} run{'s' if len(F) > 1 else ''})")
            ax.annotate(f"{np.median(F):.3f}", (i, np.max(F)), xytext=(0, 6), textcoords="offset points",
                        ha="center", fontsize=8, color=INK2)
        ax.set_xticks(range(len(algs)))
        ax.set_xticklabels(algs, color=INK2)
        ax.set_ylabel("final best F (lower is better)", color=INK2)
        note = f"  ·  unsafe, not shown: {', '.join(hidden)}" if hidden else "  ·  every run safe"
        ax.set_title(f"{size} city{note}", loc="left", fontsize=10.5, color=INK)
        ax.margins(y=0.12)
    top_ = _title(fig, "Spread of the results over the seeds",
           "Box = middle 50 % of the safe runs, black line = their median (written above), dots = every run "
           "(GA ●, PSO ■, ACO ▲); "
           "DP is deterministic: one run (◆).")
    fig.tight_layout(rect=(0, 0, 1, top_))
    _save(fig, out / "distribution.png")


# الجودة مقابل الزمن
def quality_vs_time(main, out):
    sizes = _sizes(main)
    fig, axs = plt.subplots(1, len(sizes), figsize=(5.0 * len(sizes), 5.2), squeeze=False)
    for ax, size in zip(axs[0], sizes):
        _style(ax)
        d = main[(main["size"] == size) & (main["F"] < UNSAFE)]
        for alg in [a for a in ORDER if a in set(d["algorithm"])]:
            e = d[d["algorithm"] == alg]
            ax.scatter(e["cpu_s"], e["F"], s=30 if len(e) > 1 else 70, marker=MARKERS[alg], color=COLORS[alg],
                       ec=SURFACE, lw=0.8, alpha=0.9, label=f"{alg}: {e['cpu_s'].median():.1f} s, "
                                                             f"median F {e['F'].median():.3f}")
        ax.set_xscale("log")
        _plain(ax.xaxis)
        ax.set_xlabel("CPU time of the run (s, log scale)", color=INK2)
        ax.set_ylabel("final best F (lower is better)", color=INK2)
        ax.set_title(f"{size} city", loc="left", fontsize=10.5, color=INK)
        ax.legend(frameon=False, fontsize=8, labelcolor=INK2, loc="upper center", bbox_to_anchor=(0.5, -0.2),
                  ncol=2)
        ax.margins(y=0.15)
    top_ = _title(fig, "Quality against cost: every run of the main experiment",
           "Lower and further left is better. CPU time = processor time of the run itself. The 20 seeds ran in two "
           "sittings of a cloud machine whose speed changed, so compare costs in cost.png (one sitting).")
    fig.tight_layout(rect=(0, 0, 1, top_))
    _save(fig, out / "quality_vs_time.png")


# الزمن والذاكرة
def cost(summary, out, one_sitting=False):
    sizes = [s for s in SIZES if s in set(summary["size"])]
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.4))
    width = 0.2
    for ax, col, err, label, log in ((axs[0], "mean_cpu_s", "std_cpu_s", "mean CPU time per run (s, log scale)",
                                      True),
                                     (axs[1], "mean_memory_mb", None, "peak extra memory per run (MB)", False)):
        _style(ax, "y")
        for k, alg in enumerate(ORDER):
            s = summary[summary["algorithm"] == alg].set_index("size").reindex(sizes)
            x = np.arange(len(sizes)) + (k - 1.5) * width
            vals = s[col].values.astype(float)
            ax.bar(x, vals, width=width * 0.92, color=COLORS[alg], label=alg,
                   yerr=None if err is None else s[err].values, error_kw={"ecolor": INK2, "lw": 0.8, "capsize": 2})
            for xi, v in zip(x, vals):
                if np.isfinite(v):
                    ax.annotate(f"{v:.1f}" if v < 10 else f"{v:.0f}", (xi, v), xytext=(0, 3),
                                textcoords="offset points", ha="center", fontsize=7.5, color=INK2)
        ax.set_xticks(range(len(sizes)))
        ax.set_xticklabels([f"{s} city" for s in sizes], color=INK2)
        ax.set_ylabel(label, color=INK2)
        if log:
            ax.set_yscale("log")
            _plain(ax.yaxis)
        ax.legend(frameon=False, fontsize=8.5, labelcolor=INK2, ncol=4, loc="upper left")
        ax.margins(y=0.15)
    axs[0].set_title("CPU time (bars = mean, lines = std over the seeds)", loc="left", fontsize=10.5, color=INK)
    axs[1].set_title("Memory: peak above the process at the start of the run", loc="left", fontsize=10.5, color=INK)
    top_ = _title(fig, "Cost of one run (same budget of evaluations for GA, PSO and ACO; DP = one exact search)"
                  + ("  ·  measured in one sitting" if one_sitting else ""))
    fig.tight_layout(rect=(0, 0, 1, top_))
    _save(fig, out / "cost.png")


# مصفوفة ويلكوكسون
def wilcoxon_matrix(wil, out, alpha=0.05):
    sizes = [s for s in SIZES if s in set(wil["size"])]
    fig, axs = plt.subplots(1, len(sizes), figsize=(4.4 * len(sizes), 4.6), squeeze=False)
    better, worse, same = "#0ca30c", "#d03b3b", "#e9e8e2"          # ألوان الحالة (مع كلمة في كل خلية)
    for ax, size in zip(axs[0], sizes):
        w = wil[wil["size"] == size]
        algs = [a for a in ORDER if a in set(w["first"]) | set(w["second"])]
        n = len(algs)
        ax.set_xlim(-0.5, n - 0.5)
        ax.set_ylim(n - 0.5, -0.5)
        for i, A in enumerate(algs):
            for j, B in enumerate(algs):
                if i == j:
                    ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fc=SURFACE, ec=GRID))
                    continue
                r = w[((w["first"] == A) & (w["second"] == B)) | ((w["first"] == B) & (w["second"] == A))].iloc[0]
                sig = r["p_holm"] < alpha
                a_wins = (r["median_diff"] < 0) == (r["first"] == A)
                fc = (better if a_wins else worse) if sig else same
                ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fc=fc, ec=SURFACE, lw=2,
                                           alpha=0.85 if sig else 1))
                a12 = r["A12"] if r["first"] == A else 1 - r["A12"]
                txt = ("better" if a_wins else "worse") if sig else "n.s."
                p = r["p_holm"]
                ptxt = f"p={p:.0e}" if p < 1e-3 else f"p={p:.3f}"
                ax.text(j, i - 0.12, txt, ha="center", va="center", fontsize=8.5,
                        color=SURFACE if sig else INK2, fontweight="bold")
                ax.text(j, i + 0.18, f"{ptxt}\nA12={a12:.2f}", ha="center", va="center", fontsize=6.8,
                        color=SURFACE if sig else INK2)
        ax.set_xticks(range(n))
        ax.set_yticks(range(n))
        ax.set_xticklabels(algs, color=INK2)
        ax.set_yticklabels(algs, color=INK2)
        ax.tick_params(length=0)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_title(f"{size} city: row compared with column", loc="left", fontsize=10, color=INK)
    handles = [Patch(fc=better, label="row significantly better (lower F)"),
               Patch(fc=worse, label="row significantly worse"),
               Patch(fc=same, label="no significant difference")]
    fig.legend(handles=handles, loc="lower left", ncol=3, frameon=False, fontsize=8.5, labelcolor=INK2)
    top_ = _title(fig, "Wilcoxon signed-rank tests between every pair (paired by seed, Holm-corrected, α = 0.05)",
           "A12 = probability that a run of the row algorithm has a lower F than a run of the column algorithm.")
    fig.tight_layout(rect=(0, 0.06, 1, top_))
    _save(fig, out / "wilcoxon.png")


# المدن العشوائية
def random_cities(rnd, rsum, out):
    sizes = _sizes(rnd)
    fig, axs = plt.subplots(1, len(sizes), figsize=(5.2 * len(sizes), 5.6), squeeze=False)
    for ax, size in zip(axs[0], sizes):
        _style(ax, "y")
        d = rnd[rnd["size"] == size]
        piv = d.pivot_table(index="city", columns="algorithm", values="F", aggfunc="mean", observed=True)
        cities = list(piv.index)
        gap = (piv.div(piv["DP"], axis=0) - 1) * 100
        finite = gap[piv < UNSAFE].stack()
        top = max(5.0, float(finite.max()) * 1.15) if len(finite) else 5.0
        bottom = min(-5.0, float(finite.min())) if len(finite) else -5.0
        bottom -= 0.06 * (top - bottom)                            # مساحة تحت أدنى نقطة
        for k, alg in enumerate([a for a in ORDER if a in piv.columns and a != "DP"]):
            x = np.arange(len(cities)) + (k - 1) * 0.18
            g = gap[alg].values
            safe = piv[alg].values < UNSAFE
            r = rsum[(rsum["size"] == size) & (rsum["algorithm"] == alg)]
            rank = f", mean rank {r['mean_rank'].iloc[0]:.1f}" if len(r) else ""
            ax.scatter(x[safe], g[safe], marker=MARKERS[alg], s=34, color=COLORS[alg], ec=SURFACE, lw=0.7,
                       zorder=3, label=f"{alg} ({int(safe.sum())}/{len(safe)} safe{rank})")
            if (~safe).any():
                ax.scatter(x[~safe], np.full((~safe).sum(), top * 0.97), marker=MARKERS[alg], s=34,
                           facecolor="none", ec=COLORS[alg], lw=1.2, zorder=3)
        rd = rsum[(rsum["size"] == size) & (rsum["algorithm"] == "DP")]
        ax.axhline(0, color=COLORS["DP"], ls=(0, (5, 3)), lw=1.5,
                   label="DP = 0 %" + (f" (mean rank {rd['mean_rank'].iloc[0]:.1f})" if len(rd) else ""))
        ax.set_ylim(bottom, top)
        ax.set_xticks(range(len(cities)))
        ax.set_xticklabels([c.split("_")[-1] for c in cities], color=INK2, fontsize=8)
        ax.set_xlabel("random city", color=INK2)
        ax.set_ylabel("F relative to DP (%; below 0 = better than DP)", color=INK2)
        ax.set_title(f"{size} cities", loc="left", fontsize=10.5, color=INK)
        h, lab = ax.get_legend_handles_labels()
        h.append(plt.Line2D([], [], marker="o", ls="", mfc="none", mec=INK2, label="hollow, top edge = unsafe plan"))
        ax.legend(handles=h, frameon=False, fontsize=7.8, labelcolor=INK2, loc="upper center",
                  bbox_to_anchor=(0.5, -0.2), ncol=2)
    top_ = _title(fig, "Ten random cities of each size: one run per algorithm and city (seed 0)",
           "Each dot is one city. Hollow markers on the top edge = the plan was unsafe in that city.")
    fig.tight_layout(rect=(0, 0, 1, top_))
    _save(fig, out / "random_cities.png")


# الحساسية
def sensitivity(sens, out):
    studies = list(dict.fromkeys(sens["study"]))
    ncol = 3
    nrow = int(np.ceil(len(studies) / ncol))
    fig, axs = plt.subplots(nrow, ncol, figsize=(5.4 * ncol, 3.2 * nrow + 0.9), squeeze=False, sharex=True)
    for ax, study in zip(axs.ravel(), studies):
        _style(ax, "x")
        s = sens[sens["study"] == study].groupby("parameter", sort=False).agg(
            spread=("spread_pct", "first"), best=("mean_F", "min"), alg=("algorithm", "first")).reset_index()
        s = s.sort_values("spread")
        y = np.arange(len(s))
        ax.barh(y, s["spread"], color=COLORS.get(s["alg"].iloc[0], INK2), height=0.62)
        for yi, v in zip(y, s["spread"]):
            ax.annotate(f"{v:.1f} %", (v, yi), xytext=(3, 0), textcoords="offset points", va="center",
                        fontsize=7.8, color=INK2)
        ax.set_yticks(y)
        ax.set_yticklabels(s["parameter"], fontsize=8, color=INK2)
        ax.set_xlabel("spread of mean F between its values (% of the default)", color=INK2, fontsize=8.5)
        n = sens[sens["study"] == study]["runs"].max()
        ax.set_title(f"{study}  ·  {n} run{'s' if n > 1 else ''} per value", loc="left", fontsize=10, color=INK)
        ax.set_xlim(0, sens["spread_pct"].max() * 1.18)
        ax.xaxis.set_tick_params(labelbottom=True)
    for ax in axs.ravel()[len(studies):]:
        ax.axis("off")
    top_ = _title(fig, "Parameter sensitivity: how much the mean F changes when one parameter changes",
           "One factor at a time around the default (GA, PSO and ACO studies, tuning seeds 1000+; DP: grid cell size "
           "and pruning). Longer bar = the algorithm is more sensitive to this parameter.")
    fig.tight_layout(rect=(0, 0, 1, top_))
    _save(fig, out / "sensitivity.png")


# أفضل الخطط
def best_paths(main, out, runs_dir):
    import json
    sizes = _sizes(main)
    fig, axs = plt.subplots(1, len(sizes), figsize=(6.0 * len(sizes), 6.6), squeeze=False)
    for ax, size in zip(axs[0], sizes):
        scn = load_scenario(city_path(size))
        hs = [b.h for b in scn.buildings]
        _top(ax, scn, Normalize(min(hs), max(hs)), labels=False, legend=False, straight=False, goal_color=INK)
        d = main[main["size"] == size]
        for alg in [a for a in ORDER if a in set(d["algorithm"])]:
            best = d[d["algorithm"] == alg].sort_values("F").iloc[0]
            r = json.loads((Path(runs_dir) / "main" / best["file"]).read_text())
            for k, p in enumerate(r["paths"]):
                p = np.array(p)
                ax.plot(p[:, 0], p[:, 1], color=COLORS[alg], lw=1.7, alpha=0.9, zorder=5,
                        label=f"{alg}  F = {best['F']:.3f} (seed {best['seed']})" if k == 0 else None)
        ax.set_title(f"{size} city", loc="left", fontsize=10.5, color=INK)
        ax.legend(frameon=True, facecolor=SURFACE, edgecolor=GRID, framealpha=0.92, fontsize=8, labelcolor=INK2,
                  loc="upper left")
    top_ = _title(fig, "Best plan of each algorithm in each main city (top view; ▲ take-off, ✕ release point, ★ fire)")
    fig.tight_layout(rect=(0, 0, 1, top_))
    _save(fig, out / "best_paths.png")


def draw_all(df, curves, summary, wil, rsum, sens, out: Path, runs_dir: Path | None = None, timing=None):
    out = Path(out)
    main = df[df["part"] == "main"]
    rnd = df[df["part"] == "random"]
    if len(main):
        convergence(main, curves, out)
        distribution(main, out)
        quality_vs_time(main, out)
        cost(timing if timing is not None else summary, out, one_sitting=timing is not None)
        if len(wil):
            wilcoxon_matrix(wil, out)
        if runs_dir is not None:
            best_paths(main, out, runs_dir)
    if len(rnd):
        random_cities(rnd, rsum, out)
    if len(sens):
        sensitivity(sens, out)


def main():
    out_dir = ROOT / "figures" / "cities"
    for size in SIZES:
        preview_city(ROOT / "scenarios" / f"{size}.json", out_dir / f"{size}.png")
        preview_random(size, out_dir / f"{size}_random.png")
        preview_hazard(ROOT / "scenarios" / f"{size}.json", ROOT / "figures" / "hazard" / f"{size}_fire0.png")
        print(f"figures/cities/{size}.png, figures/cities/{size}_random.png, figures/hazard/{size}_fire0.png")


if __name__ == "__main__":
    main()
