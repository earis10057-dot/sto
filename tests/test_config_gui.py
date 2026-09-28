import os

import pytest

from blogauto import config


def test_save_env_keeps_comments_and_updates_environ(project, monkeypatch):
    (project / ".env").write_text("# 주석\nANTHROPIC_API_KEY=\nNAVER_CLIENT_ID=old\n", encoding="utf-8")
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)
    config.save_env({"NAVER_CLIENT_ID": "new", "WEBHOOK_URL": "https://hook"})
    text = (project / ".env").read_text(encoding="utf-8")
    assert text == "# 주석\nANTHROPIC_API_KEY=\nNAVER_CLIENT_ID=new\nWEBHOOK_URL=https://hook\n"
    assert os.environ["NAVER_CLIENT_ID"] == "new"
    monkeypatch.delenv("WEBHOOK_URL")


def test_user_settings_override_without_touching_settings_yaml(project):
    original = (project / "config" / "settings.yaml").read_text(encoding="utf-8")
    config.save_user_settings({"seed_keywords": ["기초연금"], "images": {"blog_name": "살림노트"}})
    config.save_user_settings({"images": {"theme": "mint"}})
    s = config.load_settings()
    assert s["seed_keywords"] == ["기초연금"]
    assert s["images"]["blog_name"] == "살림노트" and s["images"]["theme"] == "mint"
    assert s["images"]["badge"] == "2026 최신"  # settings.yaml 값은 유지
    assert (project / "config" / "settings.yaml").read_text(encoding="utf-8") == original


def test_gui_builds(project, monkeypatch):
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
        root.destroy()
    except tk.TclError:
        pytest.skip("화면(디스플레이)이 없는 환경")
    import sys
    from blogauto import gui
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    stdout, stderr = sys.stdout, sys.stderr
    app = gui.App()
    try:
        app.update()
        assert app.nb.index("end") == 3
        assert app.seeds.get("1.0", "end").strip().startswith("근로장려금")
    finally:
        app.destroy()
        sys.stdout, sys.stderr = stdout, stderr
