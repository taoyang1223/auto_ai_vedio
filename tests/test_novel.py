import json

from auto_video.job_builder import build_jobs
from auto_video.novel import apply_novel_chapter, draft_novel_chapter, load_novel_store
from auto_video.project import load_project


CHAPTER_TEXT = """
夜雨落在青石客栈，林舟说：“今晚不能再等。”
苏眠问：“你确定那个人会来？”
林舟看向窗外，雨水沿着灯笼往下淌，青石客栈中只剩下两人的呼吸声。
苏眠站起身，把袖中的银簪压在桌上，她的眼神比雨夜更冷。
两人来到后院石井旁，远处的马蹄声从巷口逼近。
"""


def test_novel_chapter_draft_tracks_20_minute_character_scene_and_voice(demo_project_files):
    project = load_project(demo_project_files)

    draft = draft_novel_chapter(
        project,
        {
            "chapter_text": CHAPTER_TEXT,
            "title": "雨夜客栈",
            "target_minutes": 20,
            "shot_seconds": 12,
            "provider": "mock",
        },
    )

    names = {item["name"] for item in draft["characters"]}
    scene_names = {item["name"] for item in draft["scenes"]}
    voices = {item["voice"] for item in draft["characters"] if item["name"] in {"林舟", "苏眠"}}

    assert draft["meta"]["target_minutes"] == 20
    assert draft["meta"]["shot_count"] == 100
    assert draft["chapter"]["duration"] == 1200
    assert {"旁白", "林舟", "苏眠"}.issubset(names)
    assert any("青石客栈" in name for name in scene_names)
    assert len(voices) == 2
    assert draft["shots"][0]["speaker"]
    assert draft["shots"][0]["voice"]
    assert draft["shots"][0]["scene"]
    assert draft["shots"][0]["characters"]


def test_apply_novel_chapter_writes_identity_assets_and_job_metadata(demo_project_files):
    project = load_project(demo_project_files)
    draft = draft_novel_chapter(
        project,
        {
            "chapter_text": CHAPTER_TEXT,
            "title": "雨夜客栈",
            "target_minutes": 1,
            "shot_seconds": 6,
            "provider": "mock",
        },
    )

    result = apply_novel_chapter(demo_project_files, {"draft": draft})
    reloaded = load_project(demo_project_files)
    store = load_novel_store(demo_project_files)
    first_shot = reloaded.shots[0]
    jobs = build_jobs(reloaded, kind="audio", provider_name="local_tts")

    assert result["applied"] == 10
    assert store["chapters"][0]["title"] == "雨夜客栈"
    assert first_shot.speaker
    assert first_shot.voice
    assert first_shot.scene
    assert first_shot.characters
    assert any(ref.role == "voice_reference" and ref.usage == "preserve_voice" for ref in first_shot.refs)
    assert jobs[0].metadata["speaker"] == first_shot.speaker
    assert jobs[0].metadata["voice"] == first_shot.voice

    for character in store["characters"]:
        assert (demo_project_files / "assets" / "novel" / "characters" / f"{character['id']}.txt").exists()
        assert (demo_project_files / "assets" / "novel" / "voices" / f"{character['id']}.txt").exists()
    for scene in store["scenes"]:
        assert (demo_project_files / "assets" / "novel" / "scenes" / f"{scene['id']}.txt").exists()

    saved = json.loads((demo_project_files / "shots.json").read_text(encoding="utf-8"))
    assert saved["shots"][0]["voice"] == first_shot.voice
