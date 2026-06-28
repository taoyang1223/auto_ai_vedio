import json
import subprocess
from pathlib import Path

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
    inn_scene = next(item for item in draft["scenes"] if "青石客栈" in item["name"])

    assert draft["meta"]["target_minutes"] == 20
    assert draft["meta"]["shot_count"] == 100
    assert draft["chapter"]["duration"] == 1200
    assert {"旁白", "林舟", "苏眠"}.issubset(names)
    assert any("青石客栈" in name for name in scene_names)
    assert len(voices) == 2
    assert all(item["wardrobe_profile"] for item in draft["characters"])
    assert "雨夜" in inn_scene["wardrobe_prompt"]
    assert draft["shots"][0]["speaker"]
    assert draft["shots"][0]["voice"]
    assert draft["shots"][0]["scene"]
    assert draft["shots"][0]["characters"]
    assert "穿搭规则" in draft["shots"][0]["wardrobe"]
    assert "服装" in draft["shots"][0]["visual_prompt"]


def test_novel_chapter_draft_uses_codex_analyzer_for_entities_and_prompts(demo_project_files, monkeypatch):
    calls: list[tuple[list[str], str]] = []

    def fake_which(command: str):
        return "/usr/local/bin/codex" if command == "codex" else None

    def fake_run(command, *, cwd, input, capture_output, text, timeout, check):
        calls.append((list(command), input))
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "characters": [
                        {
                            "name": "林砚",
                            "gender": "male",
                            "aliases": ["林砚先生"],
                            "visual_profile": "林砚：苍白但清醒的青年，黑发，病号服外套深灰披肩，眼神警惕",
                            "wardrobe_profile": "林砚基础服装：浅色病号服，深灰披肩，左腕旧手机作为识别物",
                            "voice_profile": "年轻男性，压低、紧绷、疑惑的音色",
                        },
                        {
                            "name": "床边女人",
                            "gender": "female",
                            "aliases": ["女人"],
                            "visual_profile": "床边女人：专业冷静的医护女性，短发，银白制服，动作克制",
                            "wardrobe_profile": "床边女人基础服装：银白医疗制服，胸牌和蓝色袖标作为识别物",
                            "voice_profile": "成年女性，温柔但职业化的音色",
                        },
                    ],
                    "scenes": [
                        {
                            "name": "燃烧金钱的病房",
                            "style_prompt": "未来医疗病房，冬眠舱、生命维持系统和昂贵设备环绕，冷白灯光，空间整洁但压迫",
                            "lighting": "冷白医疗灯与仪器微光",
                            "continuity": "冬眠舱在床侧，生命维持系统靠墙，医护设备固定在床尾",
                            "wardrobe_prompt": "医疗室内服装：病号服、医护制服、保暖披肩，保持角色识别物",
                        }
                    ],
                    "beats": [
                        {
                            "summary": "林砚在冬眠舱旁醒来，床边女人以职业化温柔欢迎他回来。",
                            "scene": "燃烧金钱的病房",
                            "speaker": "床边女人",
                            "characters": ["林砚", "床边女人"],
                            "visual_prompt": "future medical room, cryosleep pod, young man waking in hospital bed, female clinician beside bed, tense eye contact, cinematic close shot",
                            "camera_motion": "缓慢推近林砚的脸和床边女人的反应",
                            "environment_motion": "生命维持屏幕微微闪烁，冷光在金属设备上流动",
                            "performance": "床边女人开口说话，林砚喉结滚动，表情从茫然转为警惕",
                            "lighting": "冷白医疗灯，屏幕微光补光",
                            "audio_intent": "床边女人对白与口型同步，林砚呼吸压低",
                            "wardrobe": "林砚穿浅色病号服和深灰披肩，床边女人穿银白医疗制服",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("auto_video.novel_analyzer.shutil.which", fake_which)
    monkeypatch.setattr("auto_video.novel_analyzer.subprocess.run", fake_run)

    project = load_project(demo_project_files)
    draft = draft_novel_chapter(
        project,
        {
            "chapter_text": (
                "床边的女人看着他，眼神里带着一种专业训练过的温柔。"
                "“公历2497年。”她说，“林砚先生，欢迎回来。”"
                "林砚摸索那部旧手机，或者说，那是他最后一点常识。"
            ),
            "title": "醒来",
            "target_minutes": 1,
            "shot_seconds": 30,
            "provider": "mock",
            "analyzer": "codex",
        },
    )

    names = {item["name"] for item in draft["characters"]}
    scene_names = {item["name"] for item in draft["scenes"]}

    assert calls
    assert "--output-schema" in calls[0][0]
    assert "--sandbox" in calls[0][0]
    assert draft["meta"]["analyzer"] == "codex"
    assert {"旁白", "林砚", "床边女人"}.issubset(names)
    assert "或者" not in names
    assert "他手里" not in scene_names
    assert scene_names == {"燃烧金钱的病房"}
    assert "future medical room" in draft["shots"][0]["visual_prompt"]
    assert draft["shots"][0]["speaker"] == next(item["id"] for item in draft["characters"] if item["name"] == "床边女人")


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
    assert first_shot.wardrobe
    assert any(ref.role == "voice_reference" and ref.usage == "preserve_voice" for ref in first_shot.refs)
    assert jobs[0].metadata["speaker"] == first_shot.speaker
    assert jobs[0].metadata["voice"] == first_shot.voice

    for character in store["characters"]:
        character_asset = demo_project_files / "assets" / "novel" / "characters" / f"{character['id']}.txt"
        assert character_asset.exists()
        assert "wardrobe_profile" in character_asset.read_text(encoding="utf-8")
        assert (demo_project_files / "assets" / "novel" / "voices" / f"{character['id']}.txt").exists()
    for scene in store["scenes"]:
        scene_asset = demo_project_files / "assets" / "novel" / "scenes" / f"{scene['id']}.txt"
        assert scene_asset.exists()
        assert "wardrobe_prompt" in scene_asset.read_text(encoding="utf-8")

    saved = json.loads((demo_project_files / "shots.json").read_text(encoding="utf-8"))
    assert saved["shots"][0]["voice"] == first_shot.voice
    assert saved["shots"][0]["wardrobe"] == first_shot.wardrobe
