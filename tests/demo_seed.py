"""Seed a demo data folder with processed fixtures (mock AI), then run the app. For UI checks only."""
import os, sys, socket, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("CLIPHUNTER_DATA", "/tmp/ch_demo/data")
os.environ.setdefault("CLIPHUNTER_APPROVED", "/tmp/ch_demo/approved")
os.environ.setdefault("CLIPHUNTER_PORT", "7861")
from tests import mock_ai, fixtures
from core import config, db, media, pipeline, worker
mock_ai.start(9997); time.sleep(0.8)
db.init()
config.save(dict(config.DEFAULTS, ai_provider="groq", ai_base_url="http://127.0.0.1:9997/v1", ai_key="demo",
                 ai_model="mock-vision", ai_min_gap_sec=0, font="DejaVu Sans", export_quality="small"))
if not db.query("SELECT id FROM recordings"):
    for name in sys.argv[1:] or ["noisy_ordinary", "clutch", "buildup", "silent_fail", "duplicates"]:
        path, chat_path = fixtures.make(name, os.path.join(ROOT, "tests", ".media"))
        res = worker.add_source(path, fixtures.FIXTURES[name]["profile"], display_name=name.replace("_", " ").title())
        worker.jobs.get_nowait()
        if chat_path:
            db.update("recordings", res["recording_id"], chat_path=chat_path, chat_mode="rel")
        pipeline.transcribe_context = (lambda n: lambda raw, st, source=None, ctx_start=0.0: fixtures.words_for(n, ctx_start, media.duration(raw)))(name)
        worker.process_vod(res["recording_id"])
        print("seeded", name, flush=True)
import app
sys.argv.append("--no-browser")
app.main()
