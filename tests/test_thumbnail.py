import asyncio, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helper import thumbnail  # noqa: E402


class NS:
    def __init__(self, **kw): self.__dict__.update(kw)


class FakeMsg:
    def __init__(self, video=None, document=None):
        self.video, self.document, self.copied = video, document, []
    async def copy(self, **kw): self.copied.append(kw); return "copied"


class FakeClient:
    def __init__(self, thumb=""):
        self.custom_thumb, self.name, self.calls = thumb, "t", []
        self.LOGGER = lambda *a: NS(info=print, warning=print)
    async def download_media(self, msg, file_name=None):
        p = os.path.join(file_name, "f.mp4"); open(p, "wb").write(b"x"); return p
    async def send_video(self, **kw): self.calls.append(("video", kw)); return "video"
    async def send_document(self, **kw): self.calls.append(("doc", kw)); return "doc"


def run(c): return asyncio.new_event_loop().run_until_complete(c)


class SendTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.t = os.path.join(self.d, "t.jpg"); open(self.t, "wb").write(b"j")
    def tearDown(self): shutil.rmtree(self.d, ignore_errors=True)

    def test_no_thumb_copies(self):
        m = FakeMsg(video=NS(file_size=10))
        self.assertEqual(run(thumbnail.send(FakeClient(""), m, 5, "cap", None, False)), "copied")

    def test_video_with_thumb_is_reuploaded(self):
        c, m = FakeClient(self.t), FakeMsg(video=NS(file_size=10, duration=3, width=640, height=360, file_name="a.mp4"))
        self.assertEqual(run(thumbnail.send(c, m, 5, "cap", None, True)), "video")
        kw = c.calls[0][1]
        self.assertEqual((kw["thumb"], kw["caption"], kw["protect_content"]), (self.t, "cap", True))
        self.assertFalse(m.copied)

    def test_document_with_thumb(self):
        c, m = FakeClient(self.t), FakeMsg(document=NS(file_size=10, file_name="a.pdf"))
        self.assertEqual(run(thumbnail.send(c, m, 5, "", None, False)), "doc")
        self.assertIsNone(c.calls[0][1]["caption"])

    def test_big_file_and_other_media_are_copied(self):
        big = FakeMsg(video=NS(file_size=thumbnail.MAX_FILE + 1))
        self.assertEqual(run(thumbnail.send(FakeClient(self.t), big, 5, "c", None, False)), "copied")
        self.assertEqual(run(thumbnail.send(FakeClient(self.t), FakeMsg(), 5, "c", None, False)), "copied")

    def test_failure_falls_back_to_copy(self):
        c, m = FakeClient(self.t), FakeMsg(document=NS(file_size=10, file_name="a"))
        async def boom(**kw): raise RuntimeError("x")
        c.send_document = boom
        self.assertEqual(run(thumbnail.send(c, m, 5, "c", None, False)), "copied")

    def test_missing_thumb_file_is_ignored(self):
        c, m = FakeClient(os.path.join(self.d, "gone.jpg")), FakeMsg(video=NS(file_size=1))
        self.assertEqual(run(thumbnail.send(c, m, 5, "c", None, False)), "copied")


class SwitchAndSafeTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(); self.t = os.path.join(self.d, "t.jpg"); open(self.t, "wb").write(b"j")
    def tearDown(self): shutil.rmtree(self.d, ignore_errors=True)

    def test_switch_off_keeps_the_image_but_stops_using_it(self):
        c = FakeClient(self.t); c.thumb_enabled = False
        self.assertEqual(thumbnail.exists(c), self.t)
        self.assertEqual(thumbnail.active(c), "")
        m = FakeMsg(video=NS(file_size=10, duration=1, width=1, height=1, file_name="a.mp4"))
        self.assertEqual(run(thumbnail.send(c, m, 5, "cap", None, False)), "copied")
        c.thumb_enabled = True
        self.assertEqual(thumbnail.active(c), self.t)

    def test_refused_custom_caption_is_retried_plain(self):
        class M(FakeMsg):
            async def copy(self, **kw):
                self.copied.append(kw)
                if kw["caption"] != "plain": raise RuntimeError("BUTTON_URL_INVALID")
                return "ok"
        m, c = M(), FakeClient("")
        self.assertEqual(run(thumbnail.send_safe(c, m, 5, "custom", "mk", False, "plain", None)), "ok")
        self.assertEqual([k["caption"] for k in m.copied], ["custom", "plain"])
        self.assertIsNone(m.copied[1]["reply_markup"])

    def test_plain_failure_is_not_retried(self):
        class M(FakeMsg):
            async def copy(self, **kw): self.copied.append(kw); raise RuntimeError("blocked")
        m = M()
        with self.assertRaises(RuntimeError):
            run(thumbnail.send_safe(FakeClient(""), m, 5, "plain", None, False, "plain", None))
        self.assertEqual(len(m.copied), 1)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class NormalizeTests(unittest.TestCase):
    def test_big_png_becomes_small_jpeg(self):
        d = tempfile.mkdtemp()
        try:
            src, dst = os.path.join(d, "a.png"), os.path.join(d, "o.jpg")
            async def go():
                p = await asyncio.create_subprocess_exec("ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                                                         "testsrc=size=1600x900:rate=1:duration=1", "-frames:v", "1", src)
                await p.wait()
                self.assertTrue(await thumbnail.normalize(src, dst))
            run(go())
            self.assertLessEqual(os.path.getsize(dst), thumbnail.MAX_THUMB_BYTES)
            with open(dst, "rb") as f:
                self.assertEqual(f.read(2), b"\xff\xd8")
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
