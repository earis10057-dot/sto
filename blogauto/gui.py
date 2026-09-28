"""버튼으로 쓰는 프로그램 화면 (tkinter). 실행: python -m blogauto.gui 또는 start-windows.bat · start-mac.command 더블클릭."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, scrolledtext, ttk
from typing import Any, Callable

from . import cli, config
from .config import ConfigError, load_settings, resolve
from .images.cards import THEMES
from .llm import LLMError
from .research.naver_api import NaverAPIError

KNOWN_ERRORS = (ConfigError, NaverAPIError, LLMError, FileNotFoundError, ValueError)

# (환경변수, 화면 이름, 용도, 비밀값 여부)
ENV_FIELDS = [
    ("ANTHROPIC_API_KEY", "Claude API 키", "초안 작성·주제 추천·맞춤법", True),
    ("NAVER_CLIENT_ID", "네이버 오픈API Client ID", "트렌드·블로그 검색", False),
    ("NAVER_CLIENT_SECRET", "네이버 오픈API Client Secret", "트렌드·블로그 검색", True),
    ("NAVER_AD_API_KEY", "검색광고 API 키 (액세스라이선스)", "월간 검색량", True),
    ("NAVER_AD_SECRET_KEY", "검색광고 비밀키", "월간 검색량", True),
    ("NAVER_AD_CUSTOMER_ID", "검색광고 고객 ID (CUSTOMER_ID)", "월간 검색량", False),
    ("TELEGRAM_BOT_TOKEN", "텔레그램 봇 토큰 (선택)", "공고 알림", True),
    ("TELEGRAM_CHAT_ID", "텔레그램 채팅 ID (선택)", "공고 알림", False),
    ("WEBHOOK_URL", "디스코드·슬랙 웹훅 (선택)", "공고 알림", True),
]
KOREAN_FONTS = ["Malgun Gothic", "맑은 고딕", "Apple SD Gothic Neo", "NanumGothic", "나눔고딕",
                "Noto Sans CJK KR", "WenQuanYi Zen Hei"]


def open_path(path: Path) -> None:
    """파일·폴더를 운영체제 기본 프로그램으로 연다."""
    path = Path(path)
    if not path.exists():
        messagebox.showinfo("안내", f"아직 파일이 없습니다:\n{path}")
        return
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class QueueWriter:
    """print() 출력을 화면의 작업 기록 창으로 보낸다 (작업 스레드에서도 안전)."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, s: str) -> int:
        if s:
            self.q.put(("log", s))
        return len(s)

    def flush(self) -> None:
        pass


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("네이버 블로그 도우미")
        self.geometry("1040x780")
        self.minsize(900, 680)
        self._setup_fonts()

        self.q: queue.Queue = queue.Queue()
        sys.stdout = sys.stderr = QueueWriter(self.q)  # type: ignore[assignment]
        self.busy = False
        self.action_buttons: list[ttk.Button] = []
        self.post_dir: Path | None = None
        self.settings = self._load_settings_safe()

        self._build_log()
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        self.tab_write = ttk.Frame(self.nb, padding=12)
        self.tab_research = ttk.Frame(self.nb, padding=12)
        self.tab_settings = ttk.Frame(self.nb, padding=12)
        self.nb.add(self.tab_write, text="  ✍️ 글쓰기  ")
        self.nb.add(self.tab_research, text="  🔍 리서치  ")
        self.nb.add(self.tab_settings, text="  ⚙️ 설정  ")
        self._build_write_tab()
        self._build_research_tab()
        self._build_settings_tab()

        self.after(100, self._poll)
        if not os.getenv("ANTHROPIC_API_KEY"):
            self.nb.select(self.tab_settings)
            self.after(300, lambda: messagebox.showinfo(
                "처음 오셨네요", "먼저 '설정' 탭에서 Claude API 키를 입력하고 [키 저장]을 눌러 주세요.\n"
                "네이버 키는 리서치 기능을 쓸 때만 필요합니다."))

    # ── 공통 ─────────────────────────────────────────
    def _setup_fonts(self) -> None:
        families = set(tkfont.families())
        family = next((f for f in KOREAN_FONTS if f in families), None)
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            f = tkfont.nametofont(name)
            f.configure(size=10, **({"family": family} if family else {}))
        self.big_font = tkfont.Font(family=family, size=12, weight="bold") if family else None
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Big.TButton", padding=(14, 8), **({"font": self.big_font} if self.big_font else {}))
        style.configure("Hint.TLabel", foreground="#666666")

    def _load_settings_safe(self) -> dict[str, Any]:
        try:
            return load_settings()
        except ConfigError as e:
            messagebox.showerror("설정 오류", str(e))
            return {}

    def _button(self, parent, text: str, cmd: Callable, big: bool = False, action: bool = True) -> ttk.Button:
        b = ttk.Button(parent, text=text, command=cmd, style="Big.TButton" if big else "TButton")
        if action:
            self.action_buttons.append(b)
        return b

    def _build_log(self) -> None:
        frame = ttk.Frame(self, padding=(10, 6, 10, 10))
        frame.pack(side="bottom", fill="x")
        top = ttk.Frame(frame)
        top.pack(fill="x")
        self.status = ttk.Label(top, text="준비됨")
        self.status.pack(side="left")
        self.progress = ttk.Progressbar(top, mode="indeterminate", length=220)
        self.progress.pack(side="right")
        self.log = scrolledtext.ScrolledText(frame, height=6, state="disabled", wrap="word")
        self.log.pack(fill="x", pady=(6, 0))

    def _append_log(self, s: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", s)
        self.log.see("end")
        self.log.configure(state="disabled")

    def run_task(self, label: str, fn: Callable[[], Any], on_done: Callable[[Any], None] | None = None) -> None:
        """오래 걸리는 작업은 백그라운드에서 돌리고, 결과는 화면 스레드에서 처리한다."""
        if self.busy:
            messagebox.showinfo("잠시만요", "다른 작업이 진행 중입니다. 끝난 뒤에 다시 눌러 주세요.")
            return
        self.busy = True
        for b in self.action_buttons:
            b.state(["disabled"])
        self.status.configure(text=f"⏳ {label} 중...")
        self.progress.start(12)
        self._append_log(f"\n━━ {label} ━━\n")

        def worker():
            try:
                self.settings = load_settings()
                self.q.put(("done", label, fn(), on_done))
            except KNOWN_ERRORS as e:
                self.q.put(("error", label, str(e), None))
            except Exception as e:  # 예상 못한 오류도 화면에 보여준다
                traceback.print_exc()
                self.q.put(("error", label, f"{type(e).__name__}: {e}", None))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                kind, *rest = self.q.get_nowait()
                if kind == "log":
                    self._append_log(rest[0])
                    continue
                label, payload, on_done = rest
                self.busy = False
                self.progress.stop()
                for b in self.action_buttons:
                    b.state(["!disabled"])
                if kind == "done":
                    self.status.configure(text=f"✅ {label} 완료")
                    if on_done:
                        on_done(payload)
                else:
                    self.status.configure(text=f"❌ {label} 실패")
                    self._append_log(f"❌ {payload}\n")
                    messagebox.showerror(f"{label} 실패", payload)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # ── 글쓰기 탭 ─────────────────────────────────────
    def _build_write_tab(self) -> None:
        t = self.tab_write
        t.columnconfigure(0, weight=1)
        t.columnconfigure(1, weight=1)
        t.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(t, text=" 1. 무엇을 쓸까요? ", padding=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.columnconfigure(1, weight=1)

        self.v_topic, self.v_keyword, self.v_notes = tk.StringVar(), tk.StringVar(), tk.StringVar()
        for r, (label, var, hint) in enumerate([
            ("주제", self.v_topic, "예: 2026 근로장려금 반기 신청 방법"),
            ("메인 키워드", self.v_keyword, "예: 근로장려금 반기"),
            ("추가 요청", self.v_notes, "예: 신청 방법을 단계별로 자세히 (선택)"),
        ]):
            ttk.Label(left, text=label).grid(row=r * 2, column=0, sticky="w", pady=(4, 0))
            ttk.Entry(left, textvariable=var).grid(row=r * 2, column=1, sticky="ew", pady=(4, 0))
            ttk.Label(left, text=hint, style="Hint.TLabel").grid(row=r * 2 + 1, column=1, sticky="w")

        ref_head = ttk.Frame(left)
        ref_head.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(10, 2))
        ttk.Button(ref_head, text="파일 불러오기", command=self._load_ref_file).pack(side="right")
        ttk.Label(ref_head, text="참고자료 (공고 원문 붙여넣기)").pack(side="left")
        ttk.Label(ref_head, text=" 정확도가 크게 올라가요", style="Hint.TLabel").pack(side="left")
        self.ref_text = scrolledtext.ScrolledText(left, height=10, width=40, wrap="word")
        self.ref_text.grid(row=7, column=0, columnspan=2, sticky="nsew")
        left.rowconfigure(7, weight=1)

        opts = ttk.Frame(left)
        opts.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.v_spell, self.v_apply = tk.BooleanVar(value=False), tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="맞춤법 검사", variable=self.v_spell).pack(side="left")
        ttk.Checkbutton(opts, text="수정안 바로 반영", variable=self.v_apply).pack(side="left", padx=8)
        ttk.Label(opts, text="이미지 테마").pack(side="left", padx=(12, 4))
        self.v_theme = tk.StringVar(value=self.settings.get("images", {}).get("theme", "navy"))
        ttk.Combobox(opts, textvariable=self.v_theme, values=list(THEMES), width=8, state="readonly").pack(side="left")

        self._button(left, "✍️  초안 + 이미지 만들기", self._write, big=True).grid(
            row=9, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        right = ttk.LabelFrame(t, text=" 2. 결과 ", padding=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        self.v_post = tk.StringVar(value="아직 만든 글이 없습니다.")
        ttk.Label(right, textvariable=self.v_post, style="Hint.TLabel", wraplength=440).grid(row=0, column=0, sticky="w")
        self.result = scrolledtext.ScrolledText(right, height=12, width=40, wrap="word", state="disabled")
        self.result.grid(row=1, column=0, sticky="nsew", pady=6)

        btns = ttk.Frame(right)
        btns.grid(row=2, column=0, sticky="ew")
        for i in range(2):
            btns.columnconfigure(i, weight=1)
        for i, (text, cmd) in enumerate([
            ("📋 본문 복사 (네이버에 붙여넣기)", self._copy_body),
            ("📂 결과 폴더 열기", lambda: self._open_post("")),
            ("🖼️ 이미지 폴더 열기", lambda: self._open_post("images")),
            ("🔎 점검 리포트 보기", lambda: self._open_post("check_report.md")),
            ("🗂️ 이전 글 불러오기", self._load_previous),
            ("🔁 다시 점검", self._recheck),
        ]):
            self._button(btns, text, cmd, action=False).grid(row=i // 2, column=i % 2, sticky="ew", padx=2, pady=2)

        thumb = ttk.Frame(right)
        thumb.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(thumb, text="썸네일 문구").pack(side="left")
        self.v_thumb = tk.StringVar(value="1안")
        ttk.Combobox(thumb, textvariable=self.v_thumb, values=["1안", "2안", "3안"], width=5, state="readonly").pack(side="left", padx=4)
        self._button(thumb, "🖼️ 이미지 다시 만들기", self._rerender).pack(side="left", padx=4)

    def _load_ref_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("텍스트", "*.txt *.md"), ("모든 파일", "*.*")])
        if path:
            try:
                text = Path(path).read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = Path(path).read_text(encoding="cp949")
            self.ref_text.insert("end", ("\n\n" if self.ref_text.get("1.0", "end").strip() else "") + text)

    def _write(self) -> None:
        topic, keyword = self.v_topic.get().strip(), self.v_keyword.get().strip()
        if not topic:
            messagebox.showwarning("주제를 입력해 주세요", "주제 칸이 비어 있습니다.")
            return
        notes, ref = self.v_notes.get().strip(), self.ref_text.get("1.0", "end").strip()
        spell, apply, theme = self.v_spell.get(), self.v_apply.get(), self.v_theme.get()

        def work():
            from .writer import draft
            print("✍️  초안 작성 중... (1~3분 걸릴 수 있어요)")
            post_dir, _ = draft.run(self.settings, topic, keyword=keyword or None, notes=notes,
                                    ref_texts=[ref] if ref else None)
            cli._check_and_report(post_dir, self.settings, spell=spell or apply, apply=apply)
            cli._images(post_dir, self.settings, theme)
            return post_dir

        self.run_task("초안 만들기", work, self._show_post)

    def _show_post(self, post_dir: Path) -> None:
        from .writer.draft import load_meta
        meta = load_meta(post_dir)
        self.post_dir = post_dir
        self.v_post.set(f"📁 {post_dir}")
        lines = ["[제목 후보]"] + [f"  {i}. {t}" for i, t in enumerate(meta["titles"], 1)]
        lines += ["", "[썸네일 문구]"] + [f"  {i}안. {t['main'].replace(chr(10), ' ').replace('*', '')} / {t.get('sub', '')}"
                                          for i, t in enumerate(meta.get("thumbnail_texts", []), 1)]
        lines += ["", "[해시태그]", "  " + " ".join(f"#{h}" for h in meta["hashtags"])]
        lines += ["", "[3줄 요약]"] + [f"  ✔ {s}" for s in meta["summary"]]
        if meta.get("fact_check"):
            lines += ["", "[📌 발행 전 공식 출처로 확인할 것]"] + [f"  - {f}" for f in meta["fact_check"]]
        report = post_dir / "check_report.md"
        if report.exists():
            warn = [ln for ln in report.read_text(encoding="utf-8").splitlines() if ln.startswith("- ⚠️")]
            if warn:
                lines += ["", "[점검 경고]"] + [f"  {w[2:]}" for w in warn]
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")
        self.result.insert("1.0", "\n".join(lines))
        self.result.configure(state="disabled")

    def _need_post(self) -> bool:
        if not self.post_dir:
            messagebox.showinfo("안내", "먼저 초안을 만들거나 [이전 글 불러오기]로 글을 선택해 주세요.")
            return False
        return True

    def _copy_body(self) -> None:
        if not self._need_post():
            return
        text = (self.post_dir / "draft.txt").read_text(encoding="utf-8")
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.configure(text="📋 본문을 복사했어요. 네이버 글쓰기 화면에 붙여넣으세요 (Ctrl+V).")

    def _open_post(self, sub: str) -> None:
        if self._need_post():
            open_path(self.post_dir / sub if sub else self.post_dir)

    def _load_previous(self) -> None:
        base = resolve(self.settings.get("writer", {}).get("output_dir", "output/posts"))
        base.mkdir(parents=True, exist_ok=True)
        path = filedialog.askdirectory(initialdir=str(base), title="글 폴더 선택 (meta.json 이 있는 폴더)")
        if path:
            try:
                self._show_post(Path(path))
            except FileNotFoundError as e:
                messagebox.showerror("불러오기 실패", str(e))

    def _recheck(self) -> None:
        if self._need_post():
            post_dir, spell = self.post_dir, self.v_spell.get()
            self.run_task("점검", lambda: cli._check_and_report(post_dir, self.settings, spell=spell, apply=False) or post_dir,
                          self._show_post)

    def _rerender(self) -> None:
        if self._need_post():
            post_dir, theme, thumb = self.post_dir, self.v_theme.get(), int(self.v_thumb.get()[0])
            self.run_task("이미지 만들기", lambda: cli._images(post_dir, self.settings, theme, thumb) or post_dir,
                          lambda p: open_path(p / "images"))

    # ── 리서치 탭 ─────────────────────────────────────
    def _build_research_tab(self) -> None:
        t = self.tab_research
        t.columnconfigure(0, weight=2)
        t.columnconfigure(1, weight=3)
        t.rowconfigure(1, weight=1)

        bar = ttk.Frame(t)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self._button(bar, "📊 검색량·트렌드 수집", self._keywords, big=True).pack(side="left", padx=(0, 6))
        self._button(bar, "💡 오늘의 주제 추천", self._topics, big=True).pack(side="left", padx=6)
        self._button(bar, "📢 새 공고 확인", self._monitor, big=True).pack(side="left", padx=6)
        self.v_nollm = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="주제 추천 때 AI 없이 통계만", variable=self.v_nollm).pack(side="left", padx=10)

        left = ttk.LabelFrame(t, text=" 홈판·인기글 제목 (한 줄에 하나씩 붙여넣기) ", padding=8)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.homefeed = scrolledtext.ScrolledText(left, wrap="word", width=36)
        self.homefeed.grid(row=0, column=0, sticky="nsew")
        hf = self._homefeed_path()
        if hf.exists():
            self.homefeed.insert("1.0", hf.read_text(encoding="utf-8"))
        ttk.Button(left, text="💾 저장", command=self._save_homefeed).grid(row=1, column=0, sticky="e", pady=(6, 0))

        right = ttk.LabelFrame(t, text=" 주제 후보 (더블클릭하면 글쓰기 탭으로) ", padding=8)
        right.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(right, columns=("p", "topic", "kw"), show="headings", height=12)
        for col, text, w in (("p", "우선", 44), ("topic", "주제", 250), ("kw", "메인 키워드", 130)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w, minwidth=40, stretch=col != "p", anchor="center" if col == "p" else "w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", lambda e: self._use_topic())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_topic_detail())
        self.topic_detail = tk.StringVar()
        ttk.Label(right, textvariable=self.topic_detail, wraplength=520, justify="left").grid(row=1, column=0, sticky="ew", pady=6)
        links = ttk.Frame(right)
        links.grid(row=2, column=0, sticky="ew")
        links.columnconfigure((0, 1), weight=1)
        for i, (text, cmd) in enumerate([
            ("✍️ 이 주제로 글쓰기", self._use_topic),
            ("📗 키워드 엑셀 열기", lambda: open_path(
                resolve(self.settings.get("keywords", {}).get("spreadsheet", "data/keywords.xlsx")))),
            ("📄 주제 리포트 폴더", lambda: open_path(
                resolve(self.settings.get("topics", {}).get("output_dir", "output/topics")))),
            ("📢 공고 기록 폴더", lambda: open_path(
                resolve(self.settings.get("monitor", {}).get("output_dir", "output/monitor")))),
        ]):
            ttk.Button(links, text=text, command=cmd).grid(row=i // 2, column=i % 2, sticky="ew", padx=2, pady=2)
        self.candidates: list[dict[str, Any]] = []

    def _homefeed_path(self) -> Path:
        return resolve(self.settings.get("topics", {}).get("homefeed_file", "data/homefeed.txt"))

    def _save_homefeed(self) -> None:
        path = self._homefeed_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.homefeed.get("1.0", "end").rstrip() + "\n", encoding="utf-8")
        self.status.configure(text="💾 홈판 제목을 저장했어요.")

    def _keywords(self) -> None:
        from .research import keywords

        def work():
            res = keywords.run(self.settings)
            print(f"✅ 연관 키워드 {len(res['volumes'])}개 저장 → {res['path']}")
            for kw, recent, prev, change in res["rising"][:10]:
                print(f"   📈 {kw}  {change:+.1f}%")
            return res["path"]

        self.run_task("검색량·트렌드 수집", work, lambda p: messagebox.showinfo("완료", f"엑셀에 저장했어요.\n{p}"))

    def _topics(self) -> None:
        from .research import topics
        self._save_homefeed()
        no_llm = self.v_nollm.get()

        def work():
            has_naver = bool(os.getenv("NAVER_CLIENT_ID") and os.getenv("NAVER_CLIENT_SECRET"))
            if not has_naver:
                print("ℹ️ 네이버 오픈API 키가 없어 블로그 검색은 건너뛰고 홈판 제목·엑셀 데이터만 분석합니다.")
            return topics.run(self.settings, use_llm=not no_llm, use_search=has_naver)

        self.run_task("주제 추천", work, self._show_topics)

    def _show_topics(self, res: dict[str, Any]) -> None:
        self.tree.delete(*self.tree.get_children())
        self.candidates = res.get("candidates", [])
        for i, c in enumerate(self.candidates):
            self.tree.insert("", "end", iid=str(i), values=(c["priority"], c["topic"], c["main_keyword"]))
        self.topic_detail.set(res.get("trend_summary", "") or f"패턴 통계를 저장했어요: {res['path']}")
        if not self.candidates:
            open_path(res["path"])

    def _selected_topic(self) -> dict[str, Any] | None:
        sel = self.tree.selection()
        return self.candidates[int(sel[0])] if sel else None

    def _show_topic_detail(self) -> None:
        c = self._selected_topic()
        if c:
            self.topic_detail.set(f"왜 지금: {c['why_now']}\n관점: {c['angle']}\n제목 예시: " + " / ".join(c["title_examples"]))

    def _use_topic(self) -> None:
        c = self._selected_topic()
        if not c:
            messagebox.showinfo("안내", "목록에서 주제를 먼저 선택해 주세요.")
            return
        self.v_topic.set(c["topic"])
        self.v_keyword.set(c["main_keyword"])
        self.v_notes.set(f"관점: {c['angle']}")
        self.nb.select(self.tab_write)

    def _monitor(self) -> None:
        from .research import monitor

        def work():
            res = monitor.run(self.settings)
            if not res["new"]:
                print("새로 올라온 관련 공고가 없습니다. (처음 실행이면 현재 글 목록만 기록합니다)")
            return res

        def done(res):
            if res["new"]:
                messagebox.showinfo("새 공고", f"새 공고 {len(res['new'])}건을 찾았어요. 아래 작업 기록을 확인하세요.")

        self.run_task("새 공고 확인", work, done)

    # ── 설정 탭 ───────────────────────────────────────
    def _build_settings_tab(self) -> None:
        t = self.tab_settings
        t.columnconfigure(0, weight=3)
        t.columnconfigure(1, weight=2)

        keys = ttk.LabelFrame(t, text=" API 키 ", padding=10)
        keys.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 6))
        keys.columnconfigure(1, weight=1)
        self.env_vars: dict[str, tk.StringVar] = {}
        self.env_entries: list[ttk.Entry] = []
        for r, (name, label, use, secret) in enumerate(ENV_FIELDS):
            ttk.Label(keys, text=label).grid(row=r * 2, column=0, sticky="w", pady=(4, 0), padx=(0, 8))
            var = tk.StringVar(value=os.getenv(name, ""))
            e = ttk.Entry(keys, textvariable=var, show="•" if secret else "")
            e.grid(row=r * 2, column=1, sticky="ew", pady=(4, 0))
            if secret:
                self.env_entries.append(e)
            ttk.Label(keys, text=use, style="Hint.TLabel").grid(row=r * 2 + 1, column=1, sticky="w")
            self.env_vars[name] = var
        row = len(ENV_FIELDS) * 2
        kb = ttk.Frame(keys)
        kb.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.v_show = tk.BooleanVar(value=False)
        ttk.Checkbutton(kb, text="키 보이기", variable=self.v_show, command=self._toggle_keys).pack(side="left")
        ttk.Button(kb, text="💾 키 저장", command=self._save_keys).pack(side="right")
        ttk.Label(keys, style="Hint.TLabel", justify="left", text=(
            "· Claude 키: console.anthropic.com → API Keys\n"
            "· 네이버 오픈API: developers.naver.com → 애플리케이션 등록 (데이터랩·검색 추가)\n"
            "· 검색광고 API: searchad.naver.com → 도구 → API 사용 관리\n"
            "· 키는 이 컴퓨터의 .env 파일에만 저장됩니다.")).grid(row=row + 1, column=0, columnspan=2, sticky="w", pady=(10, 0))

        blog = ttk.LabelFrame(t, text=" 내 블로그 ", padding=10)
        blog.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        blog.columnconfigure(1, weight=1)
        img = self.settings.get("images", {})
        self.v_blog_name = tk.StringVar(value=img.get("blog_name", ""))
        self.v_badge = tk.StringVar(value=img.get("badge", ""))
        ttk.Label(blog, text="블로그 이름").grid(row=0, column=0, sticky="w")
        ttk.Entry(blog, textvariable=self.v_blog_name).grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(blog, text="썸네일 배지").grid(row=1, column=0, sticky="w")
        ttk.Entry(blog, textvariable=self.v_badge).grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Label(blog, text="시드 키워드\n(한 줄에 하나)").grid(row=2, column=0, sticky="nw", pady=(6, 0))
        self.seeds = tk.Text(blog, height=7, width=24)
        self.seeds.grid(row=2, column=1, sticky="ew", pady=(6, 0))
        self.seeds.insert("1.0", "\n".join(self.settings.get("seed_keywords", [])))
        ttk.Button(blog, text="💾 저장", command=self._save_blog).grid(row=3, column=1, sticky="e", pady=(8, 0))

        files = ttk.LabelFrame(t, text=" 더 자세히 바꾸기 ", padding=10)
        files.grid(row=1, column=1, sticky="nsew", padx=(6, 0), pady=(10, 0))
        for text, rel in [
            ("📝 내 문체 가이드 (style.md)", "config/style.md"),
            ("📁 예전 글 넣는 폴더 (samples)", "config/samples"),
            ("🚫 금칙어 목록", "config/banned_words.yaml"),
            ("⚙️ 전체 설정 파일 (감시 사이트 등)", "config/settings.yaml"),
            ("🔤 폰트 폴더", "fonts"),
        ]:
            ttk.Button(files, text=text, command=lambda r=rel: open_path(config.ROOT / r)).pack(fill="x", pady=2)
        ttk.Label(files, text="설정 파일을 고친 뒤에는 프로그램을 다시 켜 주세요.", style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

    def _toggle_keys(self) -> None:
        for e in self.env_entries:
            e.configure(show="" if self.v_show.get() else "•")

    def _save_keys(self) -> None:
        config.save_env({k: v.get().strip() for k, v in self.env_vars.items()})
        filled = [label for name, label, _, _ in ENV_FIELDS if self.env_vars[name].get().strip()]
        messagebox.showinfo("저장했어요", "입력된 키: " + (", ".join(filled) if filled else "없음"))

    def _save_blog(self) -> None:
        seeds = [s.strip() for s in self.seeds.get("1.0", "end").splitlines() if s.strip()]
        config.save_user_settings({
            "seed_keywords": seeds,
            "images": {"blog_name": self.v_blog_name.get().strip(), "badge": self.v_badge.get().strip(),
                       "theme": self.v_theme.get()},
        })
        self.settings = load_settings()
        messagebox.showinfo("저장했어요", f"시드 키워드 {len(seeds)}개와 블로그 정보를 저장했어요.")


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
