from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import imaging as im
from .templates import ScaledTemplate, TemplateLibrary

HUD_FILL_PER_HEIGHT = 0.0583

FEATURES = ("ncc", "variants", "edges", "fill", "holes", "gaps", "margin", "shape", "light")


DEFAULT_WEIGHTS = {
    "ncc": 0.18,
    "variants": 0.17,
    "edges": 0.21,
    "fill": 0.11,
    "holes": 0.21,
    "gaps": 0.11,
    "margin": 0.0,
    "shape": 0.01,
    "light": 0.0,
}
DEFAULT_THRESHOLD_HIGH = 0.50
DEFAULT_THRESHOLD_LOW = 0.42


def search_region(
    game_w: int,
    game_h: int,
    fill_h_prior: float,
    width_icons: float = 2.2,
    height_frac: float = 0.13,
    roi=None,
    max_scale: float = 1.6,
) -> tuple[int, int, int, int]:
    if roi:
        rx, ry, rw, rh = roi
        x, y = int(round(rx * game_w)), int(round(ry * game_h))
        w, h = int(round(rw * game_w)), int(round(rh * game_h))
    else:
        icon_w = fill_h_prior * 1.08 * 1.2
        w = int(round(max(width_icons * icon_w, max_scale * icon_w + 8)))
        h = int(round(max(height_frac * game_h, max_scale * fill_h_prior * 1.2 + 8)))
        x, y = game_w // 2 - w // 2, 0
    x = max(0, min(x, game_w - 8))
    y = max(0, min(y, game_h - 8))
    w = max(8, min(w, game_w - x))
    h = max(8, min(h, game_h - y))
    return x, y, w, h


@dataclass
class DetectionResult:
    score: float = 0.0
    features: dict = field(default_factory=dict)
    phase: str = "gate"
    bbox: tuple[int, int, int, int] | None = None
    fill_h_native: float = 0.0
    proc_factor: float = 1.0
    red_px: int = 0
    gate_min_px: int = 0
    match_calls: int = 0
    process_ms: float = 0.0

    @property
    def center(self) -> tuple[float, float] | None:
        if not self.bbox:
            return None
        x, y, w, h = self.bbox
        return x + w / 2.0, y + h / 2.0


@dataclass
class _Track:
    x: int
    y: int
    fill_h: int
    misses: int = 0


def _match(
    img: np.ndarray, st: ScaledTemplate, integ: np.ndarray | None = None, min_mass: float = 0.3
) -> np.ndarray:
    r = cv2.matchTemplate(img, st.fill, cv2.TM_CCOEFF_NORMED)
    tw, th = st.size
    if integ is None:
        integ = cv2.integral(img, sdepth=cv2.CV_64F)
    mass = integ[th:, tw:] - integ[:-th, tw:] - integ[th:, :-tw] + integ[:-th, :-tw]
    mass = mass[: r.shape[0], : r.shape[1]]
    r[(mass < min_mass * st.fill_weight_sum) | ~np.isfinite(r)] = -1.0
    return r


def geometric_scales(center: float, lo: float, hi: float, step: float) -> list[float]:
    out = []
    k = 0
    while k <= 200:
        ups = center * step**k
        downs = center / step**k
        if k == 0:
            if lo <= center <= hi:
                out.append(center)
        else:
            if ups <= hi:
                out.append(ups)
            if downs >= lo:
                out.append(downs)
            if ups > hi and downs < lo:
                break
        k += 1
    return out


class PresenceVerifier:
    def __init__(self):
        from .resources import resource_path

        with np.load(resource_path("assets", "templates", "presence.npz"), allow_pickle=False) as data:
            self.refs = data["refs"].copy()
            self.threshold = float(data["threshold"])
        self.templates = []
        self.scale = None

    @staticmethod
    def channels(image):
        b, g, r = cv2.split(image.astype(np.float32) / 255)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        return gray, r - (g + b) / 2, im.gradient_magnitude(gray)

    def verify(self, image, anchor_center, anchor_size):
        if anchor_center is None or anchor_size <= 0:
            return None
        factor = min(1.0, 48 / anchor_size)
        scale = round(anchor_size * factor / 48, 3)
        if scale != self.scale:
            self.templates = []
            for ref in self.refs:
                for delta in (0.9, 1, 1.1):
                    size = (round(64 * scale * delta), round(60 * scale * delta))
                    self.templates.append((size, delta, self.channels(cv2.resize(ref, size))))
            self.scale = scale
        cx, cy = anchor_center
        radius = round(anchor_size * 0.85)
        x0, y0 = max(0, round(cx) - radius), max(0, round(cy) - radius)
        x1, y1 = min(image.shape[1], round(cx) + radius), min(image.shape[0], round(cy) + radius)
        crop = image[y0:y1, x0:x1]
        if crop.size == 0:
            return None
        crop = cv2.resize(crop, (round(crop.shape[1] * factor), round(crop.shape[0] * factor)))
        maps = self.channels(crop)
        best, best_score = None, self.threshold
        for (w, h), delta, refs in self.templates:
            if w > crop.shape[1] or h > crop.shape[0]:
                continue
            corr = [
                np.nan_to_num(cv2.matchTemplate(ch, ref, cv2.TM_CCOEFF_NORMED), nan=0, posinf=0, neginf=0)
                for ch, ref in zip(maps, refs)
            ]
            scores = np.sqrt(np.maximum(0, corr[2]) * np.maximum(np.abs(corr[0]), np.abs(corr[1])))
            _, score, _, loc = cv2.minMaxLoc(scores)
            center = (x0 + (loc[0] + w / 2) / factor, y0 + (loc[1] + h / 2) / factor)
            if score >= best_score and math.dist(center, anchor_center) <= 0.25 * anchor_size:
                best_score, best = score, (center, anchor_size * delta, score)
        return best


class VisualDetector:
    def __init__(
        self,
        library: TemplateLibrary,
        weights: dict | None = None,
        red: im.RedParams = im.DEFAULT_RED,
        proc_fill_h: int = 48,
        scale_range: tuple[float, float] = (0.6, 1.6),
        scale_step: float = 1.07,
        near_range: float = 1.15,
        wide_every: int = 6,
        refine_top_k: int = 3,
        track_misses_max: int = 3,
        accept_threshold: float = DEFAULT_THRESHOLD_HIGH,
        track_threshold: float = DEFAULT_THRESHOLD_LOW,
        early_reject: float = 0.30,
    ):
        self.lib = library
        self.weights = dict(DEFAULT_WEIGHTS)
        if weights:
            self.weights.update({k: float(v) for k, v in weights.items() if k in FEATURES})
        self.red = red
        self.proc_fill_h = proc_fill_h
        self.scale_range = scale_range
        self.scale_step = scale_step
        self.near_range = near_range
        self.wide_every = wide_every
        self.refine_top_k = refine_top_k
        self.track_misses_max = track_misses_max
        self.accept_threshold = accept_threshold
        self.track_threshold = track_threshold
        self.early_reject = early_reject
        self._track: _Track | None = None
        self._hint: tuple[float, float | None, float | None] | None = None
        self._since_wide = 10**9
        self.prior_fill_h_native = 0.0
        self.proc_factor = 1.0
        self.last_debug: dict = {}

    def configure(self, game_h: int, scale_override: float | None = None) -> None:
        prior = HUD_FILL_PER_HEIGHT * game_h * (scale_override or 1.0)
        self.prior_fill_h_native = prior

        self.proc_factor = min(1.0, self.proc_fill_h / prior) if prior > 0 else 1.0
        self._track = None
        self._since_wide = 10**9

    def set_hint(self, fill_h_native: float | None, cx: float | None = None, cy: float | None = None) -> None:
        self._hint = (float(fill_h_native), cx, cy) if fill_h_native else None

    def reset_tracking(self) -> None:
        self._track = None

    def detect(self, region_bgr: np.ndarray, want_debug: bool = False) -> DetectionResult:
        t0 = time.perf_counter()
        res = DetectionResult(proc_factor=self.proc_factor)
        f = self.proc_factor
        if f < 0.999:
            size = (max(8, int(round(region_bgr.shape[1] * f))), max(8, int(round(region_bgr.shape[0] * f))))
            proc = cv2.resize(region_bgr, size, interpolation=cv2.INTER_AREA)
        else:
            proc = region_bgr
        hsv = cv2.cvtColor(proc, cv2.COLOR_BGR2HSV)
        red = im.red_membership(proc, self.red, hsv)
        red_bin = red >= self.red.binary_cut
        res.red_px = int(red_bin.sum())

        prior_proc = self.prior_fill_h_native * f
        lo, hi = prior_proc * self.scale_range[0], prior_proc * self.scale_range[1]
        smallest = self.lib.get(max(12, int(round(lo))))
        res.gate_min_px = int(0.35 * float(smallest.fill_bin.sum()))
        if want_debug:
            self.last_debug = {"proc": proc, "red": red, "hsv": hsv}

        if res.red_px < res.gate_min_px:
            self._miss_track()
            res.process_ms = (time.perf_counter() - t0) * 1e3
            return res

        best = None
        if self._track is not None:
            res.phase = "B"
            best = self._search_local(
                red,
                red_bin,
                hsv,
                self._track.x,
                self._track.y,
                self._track.fill_h,
                res,
                expand=0.35,
                full=want_debug,
            )
            if best is None or best[0] < self.track_threshold:
                self._miss_track()
                if self._track is None:
                    best = None
        if best is None:
            res.phase = "A"
            best = self._search_global(red, red_bin, hsv, prior_proc, lo, hi, res, want_debug)

        if best is not None:
            score, feats, x, y, st = best
            if want_debug and feats.get("partial"):
                feats = self.verify(red, red_bin, hsv, x, y, st, full=True)
                score = self.score(feats)
            res.score = score
            res.features = feats
            res.fill_h_native = st.fill_h / f
            res.bbox = (
                int(round(x / f)),
                int(round(y / f)),
                int(round(st.size[0] / f)),
                int(round(st.size[1] / f)),
            )
            if score >= self.track_threshold:
                if self._track is None:
                    self._track = _Track(x, y, st.fill_h)
                else:
                    self._track.x, self._track.y, self._track.fill_h, self._track.misses = x, y, st.fill_h, 0
            if want_debug:
                self.last_debug.update({"x": x, "y": y, "tpl": st})
        res.process_ms = (time.perf_counter() - t0) * 1e3
        return res

    def _miss_track(self) -> None:
        if self._track is not None:
            self._track.misses += 1
            if self._track.misses >= self.track_misses_max:
                self._track = None

    def _search_global(self, red, red_bin, hsv, prior, lo, hi, res, full):
        H, W = red.shape
        best = None

        if self._hint is not None and self._hint[1] is not None:
            fh = int(round(self._hint[0] * self.proc_factor))
            st = self.lib.get(fh)
            x = int(round(self._hint[1] * self.proc_factor - st.size[0] / 2))
            y = int(round(self._hint[2] * self.proc_factor - st.size[1] / 2))
            best = self._search_local(red, red_bin, hsv, x, y, fh, res, expand=0.5, full=full)
            if best is not None and best[0] >= self.accept_threshold:
                res.phase = "A*"
                return best

        coarse = cv2.resize(red, (max(4, W // 2), max(4, H // 2)), interpolation=cv2.INTER_AREA)
        coarse_int = cv2.integral(coarse, sdepth=cv2.CV_64F)
        center = self._hint[0] * self.proc_factor if self._hint else prior
        near = geometric_scales(
            center, max(lo, center / self.near_range), min(hi, center * self.near_range), self.scale_step
        )
        tiers = [near]
        self._since_wide += 1
        if self._since_wide >= self.wide_every:
            tiers.append(
                [
                    s
                    for s in geometric_scales(prior, lo, hi, self.scale_step)
                    if all(abs(s / n - 1) > 0.02 for n in near)
                ]
            )
            self._since_wide = 0
        for scales in tiers:
            cands = []
            for s in scales:
                fh = int(round(s))
                stc = self.lib.get(max(12, int(round(fh / 2))))
                tw, th = stc.size
                if tw > coarse.shape[1] or th > coarse.shape[0]:
                    continue
                r = _match(coarse, stc, integ=coarse_int)
                res.match_calls += 1
                _, mx, _, loc = cv2.minMaxLoc(r)
                if mx > 0.2:
                    cands.append((mx, fh, loc))
            cands.sort(key=lambda c: -c[0])
            seen = []
            for mx, fh, loc in cands:
                if len(seen) >= self.refine_top_k:
                    break
                if any(abs(loc[0] - a) <= 3 and abs(loc[1] - b) <= 3 for a, b in seen):
                    continue
                seen.append(loc)
                cand = self._search_local(
                    red, red_bin, hsv, loc[0] * 2, loc[1] * 2, fh, res, expand=0.1, full=full
                )
                if cand is not None and (best is None or cand[0] > best[0]):
                    best = cand
                if best is not None and best[0] >= self.accept_threshold:
                    return best
        return best

    def _search_local(self, red, red_bin, hsv, x, y, fill_h, res, expand: float = 0.35, full: bool = False):
        H, W = red.shape
        best_m = None
        for k in (1.0, 1.04, 1 / 1.04):
            fh = int(round(fill_h * k))
            st = self.lib.get(fh)
            tw, th = st.size
            if tw > W or th > H:
                continue
            m = int(math.ceil(expand * max(tw, th))) + 2
            x0 = max(0, min(x - m, W - tw))
            y0 = max(0, min(y - m, H - th))
            x1 = min(W, max(x + tw + m, x0 + tw))
            y1 = min(H, max(y + th + m, y0 + th))
            r = _match(red[y0:y1, x0:x1], st)
            res.match_calls += 1
            _, mx, _, loc = cv2.minMaxLoc(r)
            if best_m is None or mx > best_m[0]:
                best_m = (mx, x0 + loc[0], y0 + loc[1], st)
            if k == 1.0 and mx < 0.15:
                break
        if best_m is None or best_m[0] <= -0.5:
            return None
        _, bx, by, st = best_m
        feats = self.verify(red, red_bin, hsv, bx, by, st, full=full)
        return self.score(feats), feats, bx, by, st

    def verify(self, red, red_bin, hsv, x, y, st: ScaledTemplate, full: bool = True) -> dict:
        tw, th = st.size
        p = red[y : y + th, x : x + tw]
        if p.shape != (th, tw):
            return {k: 0.0 for k in FEATURES}
        w = st.foot
        f = {
            "ncc": max(0.0, im.weighted_ncc(p, st.fill, w)),
            "fill": float((p * st.fill).sum() / max(1e-6, st.fill_weight_sum)),
            "holes": 1.0 - float(p[st.holes].mean()) if st.holes.any() else 0.5,
            "gaps": 1.0 - float(p[st.gaps].mean()) if st.gaps.any() else 0.5,
            "margin": 1.0 - float(p[st.margin].mean()) if st.margin.any() else 0.5,
        }
        if not full and self.score(f) < self.early_reject:
            out = {k: round(float(v), 4) for k, v in f.items()}
            out["partial"] = True
            return out
        pb = red_bin[y : y + th, x : x + tw]
        f["variants"] = max(0.0, max((im.weighted_ncc(p, v, w) for v in st.variants), default=0.0))
        f["edges"] = max(0.0, im.weighted_ncc(im.gradient_magnitude(p), st.grad, w))

        k = max(3, int(round(st.fill_h * 0.12)) | 1)
        closed = cv2.morphologyEx(pb.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
        hull_m = np.zeros((th, tw), np.uint8)
        pts = cv2.findNonZero(closed)
        if pts is not None and len(pts) >= 3:
            cv2.fillConvexPoly(hull_m, cv2.convexHull(pts), 1)
        tpl_hull = np.zeros((th, tw), np.uint8)
        if len(st.hull):
            cv2.fillPoly(tpl_hull, [st.hull], 1)
        union = float((hull_m | tpl_hull).sum())
        f["shape"] = float((hull_m & tpl_hull).sum()) / union if union else 0.0

        v = hsv[y : y + th, x : x + tw, 2].astype(np.float32)
        gap = st.margin & ~st.ring
        if st.ring.any() and gap.any():
            f["light"] = float(np.clip(0.5 + (v[st.ring].mean() - v[gap].mean()) / 80.0, 0.0, 1.0))
        else:
            f["light"] = 0.5
        return {k2: round(float(v2), 4) for k2, v2 in f.items()}

    def score(self, feats: dict) -> float:
        num = 0.0
        den = 0.0
        for k, wgt in self.weights.items():
            if wgt <= 0 or k not in feats:
                continue
            num += wgt * math.log(max(0.02, min(1.0, float(feats[k]))))
            den += wgt
        return math.exp(num / den) if den else 0.0
