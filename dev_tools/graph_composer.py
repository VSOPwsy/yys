"""
Interactive "build a graph" tool — captures vertices, templates, and edges
against a live `NemuIpcBackend`. Designed so a developer can sit at the
emulator, drive the UI by hand, and record one vertex/edge per minute.

Hard rules (CLAUDE.md S3 and the Phase 2 spec)
----------------------------------------------
* All frames come from `backend.screenshot()`. We never use PIL, mss, or any
  other screenshot path — that would make production-time templates mismatch
  what the recognizer sees.
* The on-screen frame is *frozen* until the user presses `R`. No video loop.
  The user drives the emulator by hand outside of this window, then refreshes
  to record against the new screen.
* Templates land in `dev_tools/composer_output/templates_staging/<path>.png`
  until the user explicitly `P`romotes them into the real `templates/` dir.
* Draft graph code is rewritten on every action so a crash never loses work.
* Every refresh saves the raw screenshot to `composer_output/screenshots/`
  for post-mortem.

Keys
----
`R` refresh • `V` mark current screen as vertex • `T` crop a template only •
`E` record an edge (then choose 1-6 for the action type) •
`W` annotate last edge (risky / tag / cost override) • `U` undo last record •
`S` save draft now • `P` promote staged templates → templates/ •
`Q` quit (offers a save first).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2  # noqa: E402

from core.input_backend.factory import get_input_backend  # noqa: E402
from core.logging_config import setup_logging, get_logger  # noqa: E402
from core.navigation import GraphAssembler, ScreenRecognizer  # noqa: E402

log = get_logger(__name__)

# --------------------------------------------------------------------------- #
# Output layout
# --------------------------------------------------------------------------- #
OUTPUT_ROOT = PROJECT_ROOT / "dev_tools" / "composer_output"
SCREENSHOT_DIR = OUTPUT_ROOT / "screenshots"
STAGING_DIR = OUTPUT_ROOT / "templates_staging"
TEMPLATES_DIR = PROJECT_ROOT / "templates"


def _ensure_dirs() -> None:
    for d in (OUTPUT_ROOT, SCREENSHOT_DIR, STAGING_DIR):
        d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Records (serializable so we can recover after a crash)
# --------------------------------------------------------------------------- #
@dataclass
class TemplateRecord:
    """One staged template: logical name + crop region + screenshot timestamp."""
    name: str            # logical, e.g. "main_menu/profile_btn"
    region: Tuple[int, int, int, int]  # (x1, y1, x2, y2) on the source screenshot
    threshold: float = 0.85
    button_var: str = ""  # variable name in the draft, e.g. "PROFILE_BTN"


@dataclass
class VertexRecord:
    id: str
    name: str
    anchor_template: str
    dwell_time: int = 500


@dataclass
class EdgeRecord:
    """All edges share this shape; per-type params live in `params`."""
    src: str
    dst: str
    edge_type: str               # "click_button" | "wait" | "press_back" | "swipe" | "click_at" | "compose"
    params: Dict[str, Any] = field(default_factory=dict)
    cost: float = 1.0
    risky: bool = False
    tags: Tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _slug_to_var(name: str) -> str:
    """logical template name -> Python identifier for the draft file."""
    return name.replace("/", "_").replace("-", "_").upper() + "_BTN"


def _ask(prompt: str, default: Optional[str] = None) -> str:
    """Console input with default. Empty input returns default."""
    suffix = f" [{default}]" if default is not None else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    return raw if raw else (default or "")


def _ask_float(prompt: str, default: float) -> float:
    raw = _ask(prompt, str(default))
    try:
        return float(raw)
    except ValueError:
        print(f"  (using default {default})")
        return default


def _ask_int(prompt: str, default: int) -> int:
    raw = _ask(prompt, str(default))
    try:
        return int(raw)
    except ValueError:
        print(f"  (using default {default})")
        return default


def _ask_yes_no(prompt: str, default: bool = False) -> bool:
    d = "y" if default else "n"
    return _ask(prompt, d).lower() in ("y", "yes", "1", "true")


def _select_roi(window: str, frame) -> Optional[Tuple[int, int, int, int]]:
    """Modal box-drag selection via OpenCV. Returns (x1, y1, x2, y2) or None."""
    r = cv2.selectROI(window, frame, showCrosshair=True, fromCenter=False)
    cv2.waitKey(1)  # let OpenCV settle
    x, y, w, h = r
    if w <= 0 or h <= 0:
        return None
    return (int(x), int(y), int(x + w), int(y + h))


def _wait_for_click(window: str) -> Optional[Tuple[int, int]]:
    """Block until the user clicks once in `window`. Returns ADB coords."""
    point: List[Tuple[int, int]] = []

    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            point.append((x, y))

    cv2.setMouseCallback(window, on_mouse)
    try:
        while not point:
            if (cv2.waitKey(20) & 0xFF) in (ord("q"), 27):
                return None
        return point[0]
    finally:
        # Detach the callback so subsequent waitKey calls aren't surprised.
        cv2.setMouseCallback(window, lambda *a: None)


# --------------------------------------------------------------------------- #
# Composer state
# --------------------------------------------------------------------------- #
class Composer:
    def __init__(self, backend, graph_for_recognition, *, session_id: str) -> None:
        self.backend = backend
        self.recognizer = ScreenRecognizer(matcher=backend.matcher)
        # Optional context graph: lets the tool tell the user what vertex
        # the current screen looks like, which speeds up edge recording.
        self.context_graph = graph_for_recognition
        self.session_id = session_id

        self.templates: List[TemplateRecord] = []
        self.vertices: List[VertexRecord] = []
        self.edges: List[EdgeRecord] = []
        # History for undo: a list of ("kind", index) tuples we can pop.
        self.history: List[Tuple[str, int]] = []
        self.current_frame = None
        self.last_screenshot_path: Optional[Path] = None

    # ------------------------------------------------------------------ #
    # Frame refresh
    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        shot = self.backend.screenshot()
        self.current_frame = shot
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = SCREENSHOT_DIR / f"{ts}.png"
        cv2.imwrite(str(path), shot)
        self.last_screenshot_path = path
        log.info("refreshed -> %s", path.name)

    def detected_vertex(self) -> Optional[str]:
        if self.current_frame is None or self.context_graph is None:
            return None
        return self.recognizer.detect_current(self.current_frame, self.context_graph)

    # ------------------------------------------------------------------ #
    # Template extraction
    # ------------------------------------------------------------------ #
    def _stage_template(
        self,
        window: str,
        *,
        suggested_name: Optional[str] = None,
        suggested_threshold: float = 0.85,
    ) -> Optional[TemplateRecord]:
        if self.current_frame is None:
            print("no frame yet — press R")
            return None
        region = _select_roi(window, self.current_frame)
        if region is None:
            print("(cancelled)")
            return None
        x1, y1, x2, y2 = region
        crop = self.current_frame[y1:y2, x1:x2]
        name = _ask("template logical name (e.g. main_menu/profile_btn)",
                    suggested_name)
        if not name:
            print("(no name; aborted)")
            return None
        threshold = _ask_float("threshold", suggested_threshold)
        out = STAGING_DIR / f"{name}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out), crop)
        log.info("staged template %s -> %s", name, out)
        rec = TemplateRecord(
            name=name,
            region=region,
            threshold=threshold,
            button_var=_slug_to_var(name),
        )
        self.templates.append(rec)
        self.history.append(("template", len(self.templates) - 1))
        return rec

    # ------------------------------------------------------------------ #
    # Action handlers
    # ------------------------------------------------------------------ #
    def mark_vertex(self, window: str) -> None:
        if self.current_frame is None:
            print("press R first")
            return
        vid = _ask("vertex id (e.g. main_menu)")
        if not vid:
            return
        name = _ask("display name", vid)
        print("now select the anchor region on the screenshot...")
        tmpl = self._stage_template(
            window,
            suggested_name=f"{vid}/anchor",
            suggested_threshold=0.9,
        )
        if tmpl is None:
            return
        dwell = _ask_int("dwell_time (ms)", 500)
        self.vertices.append(VertexRecord(
            id=vid, name=name, anchor_template=tmpl.name, dwell_time=dwell
        ))
        self.history.append(("vertex", len(self.vertices) - 1))
        print(f"  vertex {vid!r} recorded with anchor {tmpl.name!r}")

    def extract_template(self, window: str) -> None:
        self._stage_template(window)

    def _ask_src_vertex(self) -> Optional[str]:
        guess = self.detected_vertex() or (self.vertices[-1].id if self.vertices else "")
        src = _ask("source vertex id", guess)
        return src or None

    def record_edge(self, window: str) -> None:
        if self.current_frame is None:
            print("press R first")
            return
        src = self._ask_src_vertex()
        if not src:
            return
        print("edge action type:")
        print("  [1] click_button")
        print("  [2] wait")
        print("  [3] press_back")
        print("  [4] swipe")
        print("  [5] click_at")
        print("  [6] compose")
        choice = _ask("choose", "1")
        handler = {
            "1": self._edge_click_button,
            "2": self._edge_wait,
            "3": self._edge_press_back,
            "4": self._edge_swipe,
            "5": self._edge_click_at,
            "6": self._edge_compose,
        }.get(choice)
        if handler is None:
            print("unknown choice")
            return
        edge = handler(window, src)
        if edge is not None:
            self.edges.append(edge)
            self.history.append(("edge", len(self.edges) - 1))
            self._save_draft()  # auto-save after each successful edge

    def _post_action_recognize(self, src: str) -> Optional[str]:
        """After running the action, refresh + recognize. Returns dst vertex id or None."""
        time.sleep(_ask_float("post_delay seconds", 1.0))
        self.refresh()
        dst = self.detected_vertex()
        if dst is None:
            print("no known vertex matched the new screen.")
            manual = _ask("enter dst vertex manually (or blank to abort)")
            return manual or None
        confirmed = _ask_yes_no(f"recognized {dst!r} — accept as dst?", True)
        if not confirmed:
            manual = _ask("enter dst vertex manually (or blank to abort)")
            return manual or None
        return dst

    def _edge_click_button(self, window: str, src: str) -> Optional[EdgeRecord]:
        tmpl = self._stage_template(window)
        if tmpl is None:
            return None
        t0 = time.monotonic()
        # We can't fully reproduce backend.click(Button) here without
        # template_repository pointing at staging. Cheap fallback: tap the
        # center of the user-drawn region — same pixel the matcher would
        # find on a perfect template.
        x = (tmpl.region[0] + tmpl.region[2]) // 2
        y = (tmpl.region[1] + tmpl.region[3]) // 2
        log.info("click_xy(%d, %d) at staged-template center", x, y)
        self.backend.click_xy(x, y)
        dst = self._post_action_recognize(src)
        if dst is None:
            return None
        cost = round(time.monotonic() - t0, 2)
        return EdgeRecord(
            src=src, dst=dst, edge_type="click_button",
            params={"button_var": tmpl.button_var, "template": tmpl.name},
            cost=cost,
        )

    def _edge_wait(self, _window: str, src: str) -> Optional[EdgeRecord]:
        seconds = _ask_float("wait seconds", 2.0)
        time.sleep(seconds)
        dst = self._post_action_recognize(src)
        if dst is None:
            return None
        return EdgeRecord(
            src=src, dst=dst, edge_type="wait",
            params={"seconds": seconds}, cost=seconds,
        )

    def _edge_press_back(self, _window: str, src: str) -> Optional[EdgeRecord]:
        t0 = time.monotonic()
        try:
            self.backend.press_back()
        except NotImplementedError:
            print("  this backend doesn't support press_back; "
                  "use click_button on a back-button instead.")
            return None
        dst = self._post_action_recognize(src)
        if dst is None:
            return None
        return EdgeRecord(
            src=src, dst=dst, edge_type="press_back",
            cost=round(time.monotonic() - t0, 2),
        )

    def _edge_swipe(self, window: str, src: str) -> Optional[EdgeRecord]:
        print("click swipe START point...")
        start = _wait_for_click(window)
        if start is None:
            return None
        print("click swipe END point...")
        end = _wait_for_click(window)
        if end is None:
            return None
        duration = _ask_float("swipe duration seconds", 0.3)
        t0 = time.monotonic()
        self.backend.swipe(start, end, duration)
        dst = self._post_action_recognize(src)
        if dst is None:
            return None
        return EdgeRecord(
            src=src, dst=dst, edge_type="swipe",
            params={"start": start, "end": end, "duration": duration},
            cost=round(time.monotonic() - t0, 2),
        )

    def _edge_click_at(self, window: str, src: str) -> Optional[EdgeRecord]:
        print("click the target point (HARDCODED — prefer click_button)...")
        pt = _wait_for_click(window)
        if pt is None:
            return None
        t0 = time.monotonic()
        self.backend.click_xy(*pt)
        dst = self._post_action_recognize(src)
        if dst is None:
            return None
        return EdgeRecord(
            src=src, dst=dst, edge_type="click_at",
            params={"xy": pt, "_warning": "hardcoded coordinates"},
            cost=round(time.monotonic() - t0, 2),
        )

    def _edge_compose(self, window: str, src: str) -> Optional[EdgeRecord]:
        print("compose: record each sub-action; finish with empty type.")
        subs: List[Dict[str, Any]] = []
        for i in range(1, 8):
            print(f"  sub-action #{i}:")
            sub_type = _ask("type (click_button/wait/press_back/swipe/click_at)", "")
            if not sub_type:
                break
            subs.append({"type": sub_type, "note": "fill in manually in draft"})
        if not subs:
            return None
        dst = self._post_action_recognize(src)
        if dst is None:
            return None
        return EdgeRecord(
            src=src, dst=dst, edge_type="compose",
            params={"subs": subs}, cost=1.0,
        )

    def annotate_last_edge(self) -> None:
        if not self.edges:
            print("no edge to annotate")
            return
        e = self.edges[-1]
        risky = _ask_yes_no(f"risky? (currently {e.risky})", e.risky)
        tags_raw = _ask("tags (comma-separated)", ",".join(e.tags))
        cost = _ask_float("cost override", e.cost)
        self.edges[-1] = EdgeRecord(
            src=e.src, dst=e.dst, edge_type=e.edge_type, params=e.params,
            cost=cost, risky=risky,
            tags=tuple(t.strip() for t in tags_raw.split(",") if t.strip()),
        )
        self._save_draft()

    def undo(self) -> None:
        if not self.history:
            print("nothing to undo")
            return
        kind, idx = self.history.pop()
        if kind == "vertex":
            print(f"undo vertex {self.vertices[idx].id}")
            del self.vertices[idx]
        elif kind == "edge":
            print(f"undo edge {self.edges[idx].src} -> {self.edges[idx].dst}")
            del self.edges[idx]
        elif kind == "template":
            t = self.templates[idx]
            print(f"undo template {t.name}")
            staged = STAGING_DIR / f"{t.name}.png"
            if staged.exists():
                staged.unlink()
            del self.templates[idx]
        self._save_draft()

    # ------------------------------------------------------------------ #
    # Draft writing
    # ------------------------------------------------------------------ #
    def _save_draft(self) -> Path:
        out = OUTPUT_ROOT / f"draft_{self.session_id}.py"
        lines = [
            f"# Auto-generated by graph_composer at "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "# Review, then hand-edit before merging into graphs/.",
            "from core.navigation.builder import (",
            "    vertex, edge, click_button, wait, press_back, swipe_to, click_at, compose,",
            ")",
            "from core.vision import Button",
            "",
            "# === Buttons ===",
        ]
        seen: set = set()
        for t in self.templates:
            if t.button_var in seen:
                continue
            seen.add(t.button_var)
            lines.append(
                f"{t.button_var} = Button({t.name!r}, threshold={t.threshold})"
            )
        lines.extend(["", "# === Vertices ==="])
        for v in self.vertices:
            anchor_var = _slug_to_var(v.anchor_template)
            lines.append(
                f"vertex({v.id!r}, name={v.name!r}, recognizer={anchor_var}, "
                f"dwell_time={v.dwell_time})"
            )
        lines.extend(["", "# === Edges ==="])
        for e in self.edges:
            action_expr = self._render_action(e)
            extras = []
            if e.risky:
                extras.append("risky=True")
            if e.tags:
                extras.append(f"tags={list(e.tags)!r}")
            extra = ", " + ", ".join(extras) if extras else ""
            lines.append(
                f"# {e.edge_type}: {e.src} -> {e.dst}"
            )
            if e.edge_type == "click_at":
                lines.append("# WARNING: hardcoded coordinates — consider click_button")
            lines.append(
                f"edge({e.src!r}, {e.dst!r}, action={action_expr}, cost={e.cost}{extra})"
            )
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Mirror state to JSON so we can resume after a crash.
        state = {
            "templates": [asdict(t) for t in self.templates],
            "vertices": [asdict(v) for v in self.vertices],
            "edges": [asdict(e) for e in self.edges],
        }
        (OUTPUT_ROOT / f"state_{self.session_id}.json").write_text(
            json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return out

    @staticmethod
    def _render_action(e: EdgeRecord) -> str:
        p = e.params
        if e.edge_type == "click_button":
            return f"click_button({p.get('button_var', 'BUTTON_UNSET')})"
        if e.edge_type == "wait":
            return f"wait({p.get('seconds', 1.0)})"
        if e.edge_type == "press_back":
            return "press_back()"
        if e.edge_type == "swipe":
            return f"swipe_to({p['start']}, {p['end']}, duration={p['duration']})"
        if e.edge_type == "click_at":
            return f"click_at{p['xy']}"
        if e.edge_type == "compose":
            return f"compose(...)  # fill in: {p.get('subs')!r}"
        return f"# unknown edge_type: {e.edge_type}"

    # ------------------------------------------------------------------ #
    # Promotion
    # ------------------------------------------------------------------ #
    def promote_templates(self) -> None:
        if not self.templates:
            print("no staged templates")
            return
        if not _ask_yes_no(f"promote {len(self.templates)} templates "
                           f"to {TEMPLATES_DIR}?", False):
            return
        promoted = 0
        for t in self.templates:
            src = STAGING_DIR / f"{t.name}.png"
            dst = TEMPLATES_DIR / f"{t.name}.png"
            if not src.exists():
                print(f"  missing {src}; skip")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            promoted += 1
        print(f"  promoted {promoted} templates")

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    def run(self) -> None:
        window = "graph_composer"
        cv2.namedWindow(window, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(window, 960, 540)
        print("graph_composer — press H for help, R to refresh, Q to quit")
        self.refresh()

        while True:
            if self.current_frame is not None:
                preview = self.current_frame.copy()
                cv2.putText(
                    preview, f"vertex: {self.detected_vertex() or '?'}",
                    (24, preview.shape[0] - 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3, cv2.LINE_AA,
                )
                cv2.imshow(window, preview)
            key = cv2.waitKey(0) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                if self._confirm_quit():
                    break
            elif key in (ord("r"), ord("R")):
                self.refresh()
            elif key in (ord("v"), ord("V")):
                self.mark_vertex(window)
            elif key in (ord("t"), ord("T")):
                self.extract_template(window)
            elif key in (ord("e"), ord("E")):
                self.record_edge(window)
            elif key in (ord("w"), ord("W")):
                self.annotate_last_edge()
            elif key in (ord("u"), ord("U")):
                self.undo()
            elif key in (ord("s"), ord("S")):
                path = self._save_draft()
                print(f"saved draft -> {path}")
            elif key in (ord("p"), ord("P")):
                self.promote_templates()
            elif key in (ord("h"), ord("H")):
                print(__doc__)
            # Other keys: ignored.
        cv2.destroyAllWindows()

    def _confirm_quit(self) -> bool:
        if not (self.vertices or self.edges or self.templates):
            return True
        if _ask_yes_no("save draft before quitting?", True):
            path = self._save_draft()
            print(f"saved -> {path}")
        return True


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #
def _build_context_graph(spec: Optional[str]):
    """Optional graph used to identify the current screen during composing."""
    if spec is None:
        return None
    if ":" not in spec:
        raise ValueError(f"--context-graph expects 'module:callable', got {spec!r}")
    import importlib
    mod_name, fn_name = spec.split(":", 1)
    g = getattr(importlib.import_module(mod_name), fn_name)()
    if hasattr(g, "assemble"):
        return g.assemble()
    return g


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mumu", required=True,
                        help="MuMu 12 install root.")
    parser.add_argument("--instance", type=int, default=0)
    parser.add_argument("--display", type=int, default=0)
    parser.add_argument("--account-id", default="composer")
    parser.add_argument("--context-graph", default=None,
                        help="module:callable returning a GameGraph (or assembler) "
                             "used for live recognition during composing.")
    args = parser.parse_args()

    setup_logging(account_id=args.account_id)
    _ensure_dirs()

    context = _build_context_graph(args.context_graph)
    backend = get_input_backend(
        account_id=args.account_id,
        backend_name="nemu",
        mumu_folder=args.mumu,
        instance_id=args.instance,
        display_id=args.display,
    )
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    with backend:
        Composer(backend, context, session_id=session_id).run()


if __name__ == "__main__":
    main()
