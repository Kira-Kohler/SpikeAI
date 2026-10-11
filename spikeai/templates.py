from __future__ import annotations

import os
import re
from collections import OrderedDict
from dataclasses import dataclass, field

import cv2
import numpy as np

from . import imaging as im
from .logsys import log
from .resources import list_reference_pngs, load_png_unchanged, sha256_file

PAD_FRAC = 0.10
FHD_TAG = "1920x1080"


@dataclass
class Geometry:
    outer_components: int = 0
    holes: int = 0
    hexagon_vertices: int | None = None
    triangles: list[dict] = field(default_factory=list)
    triangularity: float = 0.0
    apex_down: bool = False

    def topology_score(self) -> float:
        s = 0.0
        s += 0.25 if self.outer_components == 4 else 0.0
        s += 0.25 if self.holes == 4 else 0.0
        s += 0.25 if self.hexagon_vertices in (5, 6, 7) else 0.0
        tri_ok = sum(1 for t in self.triangles if t["vertices"] == 3)
        s += 0.25 * min(tri_ok, 3) / 3.0
        return s


@dataclass
class TemplateRef:
    name: str
    path: str
    sha256: str
    width: int
    height: int
    alpha_informative: bool
    transparent_pct: float
    bgra: np.ndarray
    alpha: np.ndarray
    fill: np.ndarray
    outline: np.ndarray
    fill_bin: np.ndarray
    bbox: tuple[int, int, int, int]
    geometry: Geometry
    edge_width_px: float
    segmentation: dict | None = None
    nominal_resolution: tuple[int, int] | None = None


def analyze_geometry(fill_bin: np.ndarray) -> Geometry:
    g = Geometry()
    bb = im.tight_bbox(fill_bin)
    if bb is None:
        return g
    bx, by, bw, bh = bb
    contours, hier = cv2.findContours(fill_bin.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hier is None:
        return g
    hier = hier[0]
    min_area = 0.002 * bw * bh
    outers = [i for i, h in enumerate(hier) if h[3] == -1 and cv2.contourArea(contours[i]) >= min_area]
    holes = [i for i, h in enumerate(hier) if h[3] != -1 and cv2.contourArea(contours[i]) >= min_area * 0.5]
    g.outer_components = len(outers)
    g.holes = len(holes)

    def norm_c(c):
        m = cv2.moments(c)
        if m["m00"] == 0:
            return None
        return ((m["m10"] / m["m00"] - bx) / bw, (m["m01"] / m["m00"] - by) / bh)

    hole_info = []
    for i in holes:
        c = contours[i]
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.08 * peri, True)
        hole_info.append((i, len(approx), cv2.contourArea(c), norm_c(c)))

    pts = cv2.findNonZero(fill_bin.astype(np.uint8))
    hull = cv2.convexHull(pts)
    hm = cv2.moments(hull)
    hcx = (hm["m10"] / hm["m00"] - bx) / bw if hm["m00"] else 0.5
    hcy = (hm["m01"] / hm["m00"] - by) / bh if hm["m00"] else 0.5
    if hole_info:
        hole_info.sort(key=lambda t: (t[3][0] - hcx) ** 2 + (t[3][1] - hcy) ** 2 if t[3] else 9)
        hx = hole_info[0]
        c = contours[hx[0]]
        peri = cv2.arcLength(c, True)
        g.hexagon_vertices = len(cv2.approxPolyDP(c, 0.04 * peri, True))
        for i, nv, area, cen in hole_info[1:]:
            g.triangles.append(
                {
                    "vertices": nv,
                    "area_frac": round(area / (bw * bh), 4),
                    "center": tuple(round(v, 3) for v in cen) if cen else None,
                }
            )
    try:
        area_tri, tri = cv2.minEnclosingTriangle(hull.astype(np.float32))
        g.triangularity = float(cv2.contourArea(hull) / area_tri) if area_tri > 0 else 0.0
        ys = sorted(float(p[1]) for p in np.asarray(tri).reshape(-1, 2))
        g.apex_down = (ys[2] - ys[1]) > (ys[1] - ys[0])
    except cv2.error:
        pass
    return g


def split_outline_ring(fill_bin: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n, lab = cv2.connectedComponents(fill_bin.astype(np.uint8), connectivity=8)
    if n <= 2:
        return fill_bin, np.zeros_like(fill_bin)
    dt = cv2.distanceTransform(fill_bin.astype(np.uint8), cv2.DIST_L2, 5)
    thick = np.array([float(dt[lab == i].max()) for i in range(1, n)])
    core_ids = [i + 1 for i, t in enumerate(thick) if t >= 0.5 * thick.max()]
    core = np.isin(lab, core_ids).astype(np.uint8)
    hull = np.zeros_like(core)
    cv2.fillConvexPoly(hull, cv2.convexHull(cv2.findNonZero(core)), 1)
    hull = cv2.dilate(hull, np.ones((3, 3), np.uint8))
    ring = np.zeros_like(fill_bin)
    for i in range(1, n):
        if i in core_ids:
            continue
        comp = lab == i
        if float(hull[comp].mean()) < 0.5:
            ring[comp] = 1
    return (fill_bin & (1 - ring)).astype(np.uint8), ring.astype(np.uint8)


def edge_width(alpha: np.ndarray) -> float:
    partial = ((alpha > 0.1) & (alpha < 0.9)).sum()
    cs, _ = cv2.findContours((alpha >= 0.5).astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    per = sum(cv2.arcLength(c, True) for c in cs)
    return float(partial / per) if per > 0 else 0.0


def nominal_resolution_from_name(name: str) -> tuple[int, int] | None:
    m = re.search(r"(\d{3,4})x(\d{3,4})", name)
    return (int(m.group(1)), int(m.group(2))) if m else None


def analyze_reference(path: str) -> TemplateRef | None:
    raw = load_png_unchanged(path)
    if raw is None:
        return None
    name = os.path.basename(path)
    h, w = raw.shape[:2]
    a8 = raw[..., 3]
    informative = im.alpha_is_informative(raw)
    seg = None
    if informative:
        alpha = im.alpha_float(raw)
    else:
        alpha, rep = im.segment_opaque_icon(raw)
        seg = rep.__dict__
    bgr = raw[..., :3].copy()
    bgr[alpha <= 0.0] = 0
    bgra = np.dstack([bgr, np.clip(alpha * 255 + 0.5, 0, 255).astype(np.uint8)])
    red = im.red_membership(bgr)
    fill = (red * alpha).astype(np.float32)
    outline = (alpha * (1.0 - red)).astype(np.float32)

    fill_bin = ((alpha >= 0.5) & (red >= 0.25)).astype(np.uint8)
    fill_bin = im.largest_components(fill_bin, max(3, int(0.001 * h * w)))

    fill_bin, ring_bin = split_outline_ring(fill_bin)
    if ring_bin.any():
        keep = cv2.dilate(fill_bin, np.ones((3, 3), np.uint8)).astype(np.float32)
        ring_soft = fill * (1.0 - keep)
        fill = (fill * keep).astype(np.float32)
        outline = np.maximum(outline, ring_soft).astype(np.float32)
    bb = im.tight_bbox(fill_bin)
    if bb is None:
        log.error("La plantilla %s no contiene relleno rojo reconocible; se descarta.", name)
        return None
    ref = TemplateRef(
        name=name,
        path=path,
        sha256=sha256_file(path),
        width=w,
        height=h,
        alpha_informative=informative,
        transparent_pct=round(float((a8 == 0).mean() * 100), 2),
        bgra=bgra,
        alpha=alpha.astype(np.float32),
        fill=fill,
        outline=outline,
        fill_bin=fill_bin,
        bbox=bb,
        geometry=analyze_geometry(fill_bin),
        edge_width_px=round(edge_width(alpha), 3),
        segmentation=seg,
        nominal_resolution=nominal_resolution_from_name(name),
    )
    return ref


def padded_crop(m: np.ndarray, bbox, pad_frac=PAD_FRAC) -> np.ndarray:
    x, y, w, h = bbox
    p = int(round(pad_frac * h))
    out = np.zeros((h + 2 * p, w + 2 * p), np.float32)
    x0, y0 = x - p, y - p
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(m.shape[1], x + w + p), min(m.shape[0], y + h + p)
    out[sy0 - y0 : sy1 - y0, sx0 - x0 : sx1 - x0] = m[sy0:sy1, sx0:sx1]
    return out


def align_to(reference: np.ndarray, moving: np.ndarray) -> tuple[np.ndarray, dict]:
    warp = np.eye(2, 3, dtype=np.float32)
    info = {"method": "ecc-affine", "converged": False}
    try:
        crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-5)
        cc, warp = cv2.findTransformECC(
            reference.astype(np.float32), moving.astype(np.float32), warp, cv2.MOTION_AFFINE, crit, None, 3
        )
        info.update(converged=True, ecc=round(float(cc), 4))
    except cv2.error as e:
        info["error"] = str(e).splitlines()[-1][:120]
        warp = np.eye(2, 3, dtype=np.float32)
    A = warp[:, :2]
    sx = float(np.hypot(A[0, 0], A[1, 0]))
    sy = float(np.hypot(A[0, 1], A[1, 1]))
    info.update(
        scale_x=round(sx, 4),
        scale_y=round(sy, 4),
        aspect_distortion=round(abs(sx / sy - 1.0), 4),
        shear=round(float(A[0, 0] * A[0, 1] + A[1, 0] * A[1, 1]) / (sx * sy), 4),
        tx=round(float(warp[0, 2]), 3),
        ty=round(float(warp[1, 2]), 3),
    )
    return warp, info


def warp_map(m: np.ndarray, warp: np.ndarray) -> np.ndarray:
    return cv2.warpAffine(
        m.astype(np.float32),
        warp,
        (m.shape[1], m.shape[0]),
        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
        borderValue=0,
    )


@dataclass
class Canonical:
    fill: np.ndarray
    outline: np.ndarray
    fill_h: int
    fill_w: int
    pad: int
    variants: dict[str, np.ndarray]
    weights: dict[str, float]
    align_info: dict[str, dict]
    pairwise_ncc: dict[str, dict[str, float]]
    pairwise_iou: dict[str, dict[str, float]]


def build_canonical(refs: list[TemplateRef]) -> Canonical:
    if not refs:
        raise ValueError("No hay referencias válidas para construir la plantilla canónica.")
    fhd = [r for r in refs if FHD_TAG in r.name] or refs
    fill_h = int(round(np.mean([r.bbox[3] for r in fhd])))
    fill_w = int(round(np.mean([r.bbox[2] for r in fhd])))
    pad = int(round(PAD_FRAC * fill_h))
    size = (fill_w + 2 * pad, fill_h + 2 * pad)

    def to_frame(r: TemplateRef, m: np.ndarray) -> np.ndarray:
        return im.resize_map(padded_crop(m, r.bbox), size)

    primary = max(fhd, key=lambda r: (r.geometry.topology_score(), r.alpha_informative, -r.edge_width_px))
    ref_fill = to_frame(primary, primary.fill)
    variants, outlines, align_info = {}, {}, {}
    for r in refs:
        f = to_frame(r, r.fill)
        o = to_frame(r, r.outline)
        if r is primary:
            variants[r.name], outlines[r.name] = f, o
            align_info[r.name] = {
                "method": "referencia",
                "scale_x": 1.0,
                "scale_y": 1.0,
                "aspect_distortion": 0.0,
            }
            continue
        warp, info = align_to(ref_fill, f)
        variants[r.name] = warp_map(f, warp)
        outlines[r.name] = warp_map(o, warp)
        align_info[r.name] = info

    names = list(variants)
    ncc = {a: {} for a in names}
    iou = {a: {} for a in names}
    for a in names:
        for b in names:
            ncc[a][b] = round(im.weighted_ncc(variants[a], variants[b]), 4)
            A, B = variants[a] >= 0.5, variants[b] >= 0.5
            iou[a][b] = round(float((A & B).sum() / max(1, (A | B).sum())), 4)

    weights = {}
    for r in refs:
        consist = float(np.mean([ncc[r.name][o] for o in names if o != r.name])) if len(names) > 1 else 1.0
        q = (0.5 + 0.5 * r.geometry.topology_score()) * min(1.0, r.bbox[3] / fill_h) ** 0.5
        q *= 1.0 if r.alpha_informative else 0.8
        q *= max(0.0, consist) ** 2
        q *= 1.5 if FHD_TAG in r.name else 1.0
        weights[r.name] = round(q, 4)
    tot = sum(weights.values()) or 1.0
    fill = sum(variants[n] * (weights[n] / tot) for n in names)
    outline = sum(outlines[n] * (weights[n] / tot) for n in names)
    return Canonical(
        fill=fill.astype(np.float32),
        outline=outline.astype(np.float32),
        fill_h=fill_h,
        fill_w=fill_w,
        pad=pad,
        variants=variants,
        weights=weights,
        align_info=align_info,
        pairwise_ncc=ncc,
        pairwise_iou=iou,
    )


def verify_manifest(refs: list[TemplateRef]) -> bool:
    import json

    from .resources import derived_dir

    path = os.path.join(derived_dir(), "library.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            man = json.load(f).get("references", {})
    except FileNotFoundError:
        log.debug("Sin manifiesto de recursos derivados (%s).", path)
        return False
    except Exception as e:
        log.warning("Manifiesto de recursos derivados dañado (%s): se ignora.", e)
        return False
    ok = True
    for r in refs:
        m = man.get(r.name)
        if m is None:
            log.info("Plantilla nueva no inventariada: %s (restaura assets/templates/).", r.name)
            ok = False
        elif m.get("sha256") != r.sha256:
            log.warning(
                "La plantilla %s ha cambiado respecto al análisis guardado; se usan los datos actuales. "
                "Restaura las referencias originales.",
                r.name,
            )
            ok = False
    for name in set(man) - {r.name for r in refs}:
        log.warning("Falta la plantilla %s (estaba inventariada).", name)
        ok = False
    if ok:
        log.debug("Plantillas verificadas contra el manifiesto (%d).", len(refs))
    return ok


@dataclass
class ScaledTemplate:
    fill_h: int
    size: tuple[int, int]
    pad: int
    fill: np.ndarray
    foot: np.ndarray
    fill_bin: np.ndarray
    holes: np.ndarray
    gaps: np.ndarray
    margin: np.ndarray
    ring: np.ndarray
    grad: np.ndarray
    hull: np.ndarray
    variants: list[np.ndarray]
    fill_weight_sum: float


class TemplateLibrary:
    def __init__(self, refs: list[TemplateRef], canonical: Canonical, cache_size: int = 96):
        self.refs = refs
        self.canonical = canonical
        self._cache: OrderedDict[int, ScaledTemplate] = OrderedDict()
        self._cache_size = cache_size
        self.cache_hits = 0
        c = canonical
        fb = c.fill >= 0.5
        pts = cv2.findNonZero(fb.astype(np.uint8))
        hull_mask = np.zeros(fb.shape, np.uint8)
        cv2.fillConvexPoly(hull_mask, cv2.convexHull(pts), 1)
        self._hull_mask = hull_mask.astype(np.float32)
        k = max(1, int(round(0.03 * c.fill_h)))
        se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))

        enclosed = np.zeros(fb.shape, np.uint8)
        cs, hier = cv2.findContours(fb.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        if hier is not None:
            for i, h in enumerate(hier[0]):
                if h[3] != -1:
                    cv2.drawContours(enclosed, cs, i, 1, -1)
        enclosed &= 1 - fb.astype(np.uint8)
        gaps = ((hull_mask - fb.astype(np.uint8)).clip(0, 1) & (1 - enclosed)).astype(np.uint8)
        self._holes = cv2.erode(enclosed, se).astype(np.float32)
        self._gaps = cv2.erode(gaps, se).astype(np.float32)
        m = max(2, int(round(0.08 * c.fill_h)))
        dil = cv2.dilate(hull_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * m + 1, 2 * m + 1)))
        self._margin = (dil - hull_mask).astype(np.float32)
        self._foot = dil.astype(np.float32)
        self._ring = ((c.outline >= 0.3) & (hull_mask == 0)).astype(np.float32)

    @classmethod
    def from_folder(cls, folder: str | None = None) -> "TemplateLibrary":
        paths = list_reference_pngs(folder)
        refs = []
        for p in paths:
            r = analyze_reference(p)
            if r is not None:
                refs.append(r)
        if not refs:
            raise RuntimeError(
                "No se encontró ninguna plantilla válida de la Spike en 'assets/templates/'. "
                "Reinstala Spike AI o restaura la carpeta assets/templates/."
            )
        missing = [os.path.basename(p) for p in paths if os.path.basename(p) not in {r.name for r in refs}]
        if missing:
            log.warning("Plantillas ignoradas por estar dañadas o vacías: %s", ", ".join(missing))
        verify_manifest(refs)
        return cls(refs, build_canonical(refs))

    def aspect(self) -> float:
        return self.canonical.fill.shape[1] / self.canonical.fill.shape[0]

    def get(self, fill_h: int) -> ScaledTemplate:
        fill_h = int(max(12, fill_h))
        st = self._cache.get(fill_h)
        if st is not None:
            self._cache.move_to_end(fill_h)
            self.cache_hits += 1
            return st
        st = self._make(fill_h)
        self._cache[fill_h] = st
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return st

    def _make(self, fill_h: int) -> ScaledTemplate:
        c = self.canonical
        k = fill_h / c.fill_h
        H0, W0 = c.fill.shape
        size = (max(8, int(round(W0 * k))), max(8, int(round(H0 * k))))
        fill = im.resize_map(c.fill, size)
        foot = im.resize_map(self._foot, size)
        fill_bin = fill >= 0.5
        holes = im.resize_map(self._holes, size) >= 0.5
        gaps = im.resize_map(self._gaps, size) >= 0.5
        margin = im.resize_map(self._margin, size) >= 0.5
        ring = im.resize_map(self._ring, size) >= 0.4
        hull_m = (im.resize_map(self._hull_mask, size) >= 0.5).astype(np.uint8)
        cs, _ = cv2.findContours(hull_m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        hull = max(cs, key=cv2.contourArea) if cs else np.zeros((0, 1, 2), np.int32)
        variants = [im.resize_map(v, size) for v in c.variants.values()]
        return ScaledTemplate(
            fill_h=fill_h,
            size=size,
            pad=int(round(c.pad * k)),
            fill=fill.astype(np.float32),
            foot=foot.astype(np.float32),
            fill_bin=fill_bin,
            holes=holes,
            gaps=gaps,
            margin=margin,
            ring=ring,
            grad=im.gradient_magnitude(fill),
            hull=hull,
            variants=variants,
            fill_weight_sum=float(fill.sum()),
        )
