import json

from PIL import Image, ImageFont

from blogauto import cli, layout
from blogauto.images import cards
from blogauto.images.fonts import find_font
from blogauto.writer import checker, draft


def test_banned_words_and_structure(settings, sample_meta):
    rules = checker.load_rules(settings_path(settings))
    meta = json.loads(json.dumps(sample_meta))
    meta["sections"][0]["body"] += "\n누구나 받을 수 있고 무조건 승인돼요. 100% 확실해요."
    rep = checker.run_check(meta, draft.body_text(meta), rules, settings["checker"])
    words = {f.word for f in rep.findings}
    assert {"무조건", "100%", "무조건 승인"} <= words
    assert any("누구나" in w for w in words)  # 정규식 패턴
    assert any("짧아요" in w for w in rep.warnings)  # 분량 부족
    assert any("[확인 필요]" in w for w in rep.warnings)
    assert rep.stats["키워드 등장 횟수(띄어쓰기 무시)"] >= 3
    md = checker.report_markdown(rep)
    assert "금칙어" in md and "무조건" in md


def settings_path(settings):
    from blogauto.config import resolve
    return resolve(settings["checker"]["banned_words_file"])


def test_apply_spelling(sample_meta):
    n = checker.apply_spelling(sample_meta, [{"original": "궁금하셨죠?", "suggestion": "궁금하셨지요?", "type": "문법", "reason": ""}])
    assert n == 1 and "궁금하셨지요?" in sample_meta["intro"]


def test_draft_run_renders_files(settings, project, sample_meta, monkeypatch):
    (project / "config" / "samples" / "old.txt").write_text("예전 글 말투 샘플이에요.", encoding="utf-8")
    captured = {}

    def fake_llm(system, prompt, schema, **kw):
        captured["prompt"] = prompt
        return {k: v for k, v in sample_meta.items() if k != "topic"}

    monkeypatch.setattr(draft, "generate_json", fake_llm)
    ref = project / "ref.txt"
    ref.write_text("공고 원문: 신청기간 9월 1일~15일", encoding="utf-8")
    post_dir, meta = draft.run(settings, "근로장려금 신청", keyword="근로장려금", ref_files=[str(ref)])

    assert "예전 글 말투 샘플" in captured["prompt"] and "README" not in captured["prompt"]
    assert "공고 원문" in captured["prompt"] and "친근한 존댓말" in captured["prompt"]
    md = (post_dir / "draft.md").read_text(encoding="utf-8")
    txt = (post_dir / "draft.txt").read_text(encoding="utf-8")
    assert "## ■ 근로장려금이란?" in md and "> 일하는 저소득" in md
    assert "■ 근로장려금이란?" in txt and "[인용구]" in txt and "#근로장려금신청" in txt
    # 썸네일 → 도입부 → 목차(body_01) → 소제목2 카드(body_02) → 소제목4 카드(body_03) → 요약(body_04)
    order = [txt.index(m) for m in ("[대표 이미지(썸네일): images/thumbnail.png]", "오늘은 근로장려금",
                                    "[이미지: images/body_01.png]", "■ 근로장려금이란?",
                                    "[이미지: images/body_02.png]\n\n■ 신청 대상과 소득 기준",
                                    "[이미지: images/body_03.png]\n\n■ 홈택스 신청 방법",
                                    "[이미지: images/body_04.png]\n\n■ 한눈에 정리")]
    assert order == sorted(order)
    assert txt.count("[이미지:") == 4


def test_wrap_respects_width_and_emphasis():
    font = ImageFont.truetype(find_font(True), 60)
    runs = cards.parse_emphasis("2026 *근로장려금* 신청 방법과 지급일 총정리 가이드")
    assert [c for c, hl in runs if hl] == list("근로장려금")
    lines = cards.wrap(runs, font, 400)
    assert len(lines) > 1
    assert all(cards._width(ln, font) <= 400 for ln in lines)
    assert "".join(c for ln in lines for c, _ in ln).replace(" ", "") == "2026근로장려금신청방법과지급일총정리가이드"


def test_render_post_creates_thumbnail_and_four_16x9_images(project, sample_meta):
    (project / "post/images").mkdir(parents=True)
    (project / "post/images/section_01.png").write_bytes(b"old")  # 예전 구성 파일은 지워져야 함
    paths = cards.render_post(sample_meta, project / "post", {"theme": "mint", "badge": "2026 최신", "blog_name": "살림노트"})
    assert [p.name for p in paths] == ["thumbnail.png", "body_01.png", "body_02.png", "body_03.png", "body_04.png"]
    assert sorted(p.name for p in (project / "post/images").iterdir()) == sorted(p.name for p in paths)
    assert Image.open(paths[0]).size == (1080, 1080)
    for p in paths[1:]:
        assert Image.open(p).size == (1280, 720)


def test_thumbnail_choice(project, sample_meta, monkeypatch):
    used = []
    real = cards.thumbnail
    monkeypatch.setattr(cards, "thumbnail", lambda main, *a, **k: used.append(main) or real(main, *a, **k))
    cards.render_post(sample_meta, project / "post", {}, thumb=2)
    cards.render_post(sample_meta, project / "post", {}, thumb=9)  # 범위를 넘으면 마지막 후보
    assert used == ["근로장려금 *반기 신청*"] * 2


def test_image_sections_fallback_spreads_evenly():
    mk = lambda n, picked=None: {"sections": [{}] * n, **({"image_sections": picked} if picked is not None else {})}  # noqa: E731
    assert layout.image_sections(mk(5, [2, 4])) == [2, 4]
    assert layout.image_sections(mk(5)) == [2, 4]
    assert layout.image_sections(mk(5, [9, 2])) == [2, 4]  # 잘못된 번호 → 고르게 배치
    assert layout.image_sections(mk(6)) == [2, 5]
    assert layout.image_sections(mk(3)) == [1, 3]
    assert layout.image_sections(mk(1)) == [1]
    assert layout.body_images(mk(5, [3, 5])) == {"contents": "images/body_01.png",
                                                  "sections": {3: "images/body_02.png", 5: "images/body_03.png"},
                                                  "summary": "images/body_04.png"}


def test_cli_write_end_to_end(settings, project, sample_meta, monkeypatch, capsys):
    monkeypatch.setattr(draft, "generate_json", lambda *a, **k: {k2: v for k2, v in sample_meta.items() if k2 != "topic"})
    assert cli.main(["write", "근로장려금 신청", "-k", "근로장려금", "--theme", "coral"]) == 0
    post_dir = next((project / "output" / "posts").iterdir())
    assert (post_dir / "check_report.md").exists()
    assert len(list((post_dir / "images").glob("*.png"))) == 5
    out = capsys.readouterr().out
    assert "제목 후보" in out and "발행 전 공식 출처로 확인할 것" in out

    assert cli.main(["images", str(post_dir), "--theme", "forest", "--thumb", "2"]) == 0
    assert cli.main(["check", str(post_dir)]) == 0


def test_cli_reports_missing_credentials(settings, project, monkeypatch, capsys):
    for k in ("NAVER_AD_API_KEY", "NAVER_AD_SECRET_KEY", "NAVER_AD_CUSTOMER_ID"):
        monkeypatch.delenv(k, raising=False)
    assert cli.main(["keywords"]) == 1
    assert "NAVER_AD_API_KEY" in capsys.readouterr().err


def test_images_drop_fact_check_marker():
    assert cards._clean("9월 1일부터 신청 [확인 필요]") == "9월 1일부터 신청"
