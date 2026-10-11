from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np


@dataclass(frozen=True)
class RedParams:
    hue_tol: float = 4.5
    hue_soft: float = 2.5
    s_lo: float = 80.0
    s_hi: float = 130.0
    v_lo: float = 40.0
    v_hi: float = 75.0
    binary_cut: float = 0.5


DEFAULT_RED = RedParams()


@lru_cache(maxsize=8)
def _red_lut(p: RedParams) -> np.ndarray:
    x = np.arange(256, dtype=np.float32)
    hd = np.minimum(x, 180.0 - x)
    mh = np.clip(1.0 - (hd - p.hue_tol) / p.hue_soft, 0.0, 1.0)
    ms = np.clip((x - p.s_lo) / (p.s_hi - p.s_lo), 0.0, 1.0)
    mv = np.clip((x - p.v_lo) / (p.v_hi - p.v_lo), 0.0, 1.0)
    return np.stack([mh, ms, mv], -1).astype(np.float32).reshape(1, 256, 3)


def red_membership(bgr: np.ndarray, p: RedParams = DEFAULT_RED, hsv: np.ndarray | None = None) -> np.ndarray:
    if hsv is None:
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    m = cv2.LUT(hsv, _red_lut(p))
    return m[..., 0] * m[..., 1] * m[..., 2]


def alpha_float(bgra: np.ndarray) -> np.ndarray:
    return bgra[..., 3].astype(np.float32) / 255.0


def composite(bgra: np.ndarray, background_bgr: np.ndarray) -> np.ndarray:
    a = alpha_float(bgra)[..., None]
    out = bgra[..., :3].astype(np.float32) * a + background_bgr.astype(np.float32) * (1.0 - a)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def resize_premultiplied(bgra: np.ndarray, size_wh: tuple[int, int]) -> np.ndarray:
    w, h = size_wh
    src_h, src_w = bgra.shape[:2]
    interp = cv2.INTER_AREA if (w < src_w or h < src_h) else cv2.INTER_LINEAR
    a = alpha_float(bgra)
    pm = bgra[..., :3].astype(np.float32) * a[..., None]
    pm_r = cv2.resize(pm, (w, h), interpolation=interp)
    a_r = cv2.resize(a, (w, h), interpolation=interp)
    rgb = np.where(a_r[..., None] > 1e-4, pm_r / np.maximum(a_r[..., None], 1e-4), 0.0)
    out = np.dstack([np.clip(rgb + 0.5, 0, 255), np.clip(a_r * 255.0 + 0.5, 0, 255)]).astype(np.uint8)
    return out


def resize_map(m: np.ndarray, size_wh: tuple[int, int]) -> np.ndarray:
    w, h = size_wh
    interp = cv2.INTER_AREA if (w < m.shape[1] or h < m.shape[0]) else cv2.INTER_LINEAR
    return cv2.resize(m.astype(np.float32), (w, h), interpolation=interp)


def weighted_ncc(a: np.ndarray, b: np.ndarray, w: np.ndarray | None = None) -> float:
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    if w is None:
        w = np.ones_like(a)
    w = w.astype(np.float64)
    sw = w.sum()
    if sw <= 0:
        return 0.0

    ma = (w * a).sum() / sw
    mb = (w * b).sum() / sw
    da = w * (a - ma)
    db = w * (b - mb)
    den = np.sqrt((da * da).sum() * (db * db).sum())
    if den < 1e-12:
        return 0.0
    return float((da * db).sum() / den)


def gradient_magnitude(m: np.ndarray) -> np.ndarray:
    gx = cv2.Sobel(m.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(m.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(gx, gy)


def tight_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    return x0, y0, x1 - x0 + 1, y1 - y0 + 1


def largest_components(mask: np.ndarray, min_area: int) -> np.ndarray:
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(mask.shape, np.uint8)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            keep[lab == i] = 1
    return keep


def alpha_is_informative(bgra: np.ndarray) -> bool:
    if bgra.ndim != 3 or bgra.shape[2] != 4:
        return False
    a = bgra[..., 3]
    return float((a < 250).mean()) > 0.05


@dataclass
class SegmentationReport:
    method: str
    background_model: str
    bg_residual_sigma: float
    red_core_px: int
    ring_px: int
    removed_outside_px: int
    alpha_mean: float


def segment_opaque_icon(
    bgra_or_bgr: np.ndarray, p: RedParams = DEFAULT_RED
) -> tuple[np.ndarray, SegmentationReport]:
    bgr = bgra_or_bgr[..., :3].copy()
    h, w = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    red = red_membership(bgr, p, hsv)
    core = (red >= 0.6).astype(np.uint8)
    core = largest_components(core, min_area=max(4, int(0.002 * h * w)))

    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
    frame = np.zeros((h, w), bool)
    b = max(2, round(min(h, w) * 0.03))
    frame[:b, :] = frame[-b:, :] = frame[:, :b] = frame[:, -b:] = True
    cand = frame & (red < 0.2)
    ys, xs = np.nonzero(cand)
    X = np.column_stack([np.ones_like(xs, dtype=np.float32), xs / w, ys / h]).astype(np.float32)
    Y = lab[ys, xs]
    keep = np.ones(len(xs), bool)
    coef = None
    sigma = 1.0
    for _ in range(4):
        coef, *_ = np.linalg.lstsq(X[keep], Y[keep], rcond=None)
        res = np.linalg.norm(Y - X @ coef, axis=1)
        sigma = float(1.4826 * np.median(np.abs(res[keep] - np.median(res[keep])))) + 1e-3
        sigma = max(sigma, 1.5)
        keep = res < np.median(res[keep]) + 3.0 * sigma
    gy, gx = np.mgrid[0:h, 0:w].astype(np.float32)
    G = np.stack([np.ones_like(gx), gx / w, gy / h], axis=-1)
    bg_lab = G @ coef
    dist = np.linalg.norm(lab - bg_lab, axis=-1)
    fg_prob = np.clip((dist - 4.0 * sigma) / (10.0 * sigma), 0.0, 1.0)

    pts = cv2.findNonZero(core)
    foot = np.zeros((h, w), np.uint8)
    if pts is not None:
        hull = cv2.convexHull(pts)
        cv2.fillConvexPoly(foot, hull, 1)
        bb = cv2.boundingRect(pts)
        m = max(2, int(round(0.10 * max(bb[2], bb[3]))))
        foot = cv2.dilate(foot, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * m + 1, 2 * m + 1)))

    bg_bgr = cv2.cvtColor(np.clip(bg_lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR).astype(np.float32)
    red_ref = (
        np.median(bgr[core > 0].astype(np.float32), axis=0)
        if core.any()
        else np.array([0, 0, 170], np.float32)
    )
    d = red_ref[None, None, :] - bg_bgr
    a_red = np.clip(((bgr.astype(np.float32) - bg_bgr) * d).sum(-1) / np.maximum((d * d).sum(-1), 1e-3), 0, 1)
    near_red = cv2.dilate(core, np.ones((3, 3), np.uint8)) > 0
    a_red = np.where(near_red, np.maximum(a_red, core.astype(np.float32)), 0.0)
    a_red = np.where(red >= 0.25, a_red, a_red * (red / 0.25))

    ring = (fg_prob > 0) & (~near_red)
    alpha = np.maximum(a_red, np.where(ring, fg_prob, 0.0)) * foot
    removed = int(((fg_prob > 0.5) & (foot == 0)).sum())
    alpha = alpha.astype(np.float32)
    rep = SegmentationReport(
        method="hsv-core + robust-linear-Lab-background + convex-footprint + linear-unmixing",
        background_model=f"Lab plano lineal, coef={np.round(coef, 2).tolist() if coef is not None else None}",
        bg_residual_sigma=round(sigma, 3),
        red_core_px=int(core.sum()),
        ring_px=int(ring.sum()),
        removed_outside_px=removed,
        alpha_mean=round(float(alpha.mean()), 4),
    )
    return alpha, rep
