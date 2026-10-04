import asyncio, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helper import quality, transcode as t  # noqa: E402


class PureTests(unittest.TestCase):
    def test_parse_list(self):
        self.assertEqual(t.parse_list("720p, 144p 4k;bogus"), ["144p", "720p", "4K"])
        self.assertEqual(t.parse_list("", ["360p"]), ["360p"])

    def test_source_is_rated_by_picture_size(self):
        self.assertEqual(t.source_label(3840, 2160), "4K")
        self.assertEqual(t.source_label(3840, 1600), "4K")       # cinema crop is still 4K
        self.assertEqual(t.source_label(1920, 800), "1080p")
        self.assertEqual(t.source_label(2560, 1440), "1440p")
        self.assertEqual(t.source_label(1080, 1920), "1080p")     # portrait
        self.assertEqual(t.source_label(640, 360), "360p")

    def test_targets_never_upscale(self):
        wanted = ["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "4K"]
        self.assertEqual(t.pick_targets(3840, 2160, wanted), ["144p", "240p", "360p", "480p", "720p", "1080p", "1440p"])
        self.assertEqual(t.pick_targets(1920, 1080, wanted), ["144p", "240p", "360p", "480p", "720p"])
        self.assertEqual(t.pick_targets(1280, 720, wanted, have={"480p"}), ["144p", "240p", "360p"])
        self.assertEqual(t.pick_targets(256, 144, wanted), [])

    def test_output_name_keeps_the_group(self):
        n = t.output_name("Show.S01E01.1080p.WEB-DL.x265.mkv", "480p")
        self.assertEqual(n, "Show.S01E01.480p.WEB-DL.x264.mp4")
        self.assertEqual(quality.extract_quality(n), "480p")
        self.assertEqual(quality.group_key(n), quality.group_key("Show.S01E01.1080p.WEB-DL.x265.mkv"))
        n2 = t.output_name("My Holiday.mp4", "144p")
        self.assertEqual(n2, "My Holiday 144p.mp4")
        self.assertEqual(quality.extract_quality(n2), "144p")
        n3 = t.output_name("Movie 2160p HDR.mkv", "720p")
        self.assertEqual(quality.extract_quality(n3), "720p")
        for label in t.LADDER:
            self.assertEqual(quality.extract_quality(t.output_name("clip.mkv", label)), label)

    def test_cmd_and_progress(self):
        cmd = t.build_ffmpeg_cmd("in.mkv", "out.mp4", "720p")
        self.assertIn("min(iw,1280)", " ".join(cmd))
        self.assertIn("min(ih,720)", " ".join(cmd))
        self.assertEqual(t.fit_box("720p", portrait=True), (720, 1280))
        self.assertEqual(t.progress_seconds("out_time_us=2500000"), 2.5)
        self.assertIsNone(t.progress_seconds("frame=10"))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not installed")
class FfmpegTests(unittest.TestCase):
    def test_real_encode(self):
        async def go():
            d = tempfile.mkdtemp()
            try:
                src = os.path.join(d, "src.mkv")
                p = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=1920x800:rate=24:duration=2",
                    "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-c:a", "ac3", src)
                await p.wait()
                info = await t.probe(src)
                self.assertEqual((info["width"], info["height"]), (1920, 800))
                self.assertEqual(t.source_label(info["width"], info["height"]), "1080p")
                seen = []

                async def prog(f):
                    seen.append(f)
                for label in ("144p", "480p", "720p"):
                    out = os.path.join(d, f"o{label}.mp4")
                    rc, err = await t.run_ffmpeg(t.build_ffmpeg_cmd(src, out, label, False, "ultrafast"), info["duration"], prog)
                    self.assertEqual(rc, 0, err)
                    o = await t.probe(out)
                    self.assertLessEqual(o["height"], t.LADDER[label])
                    self.assertEqual(o["width"] % 2, 0)
                    self.assertAlmostEqual(o["width"] / o["height"], 1920 / 800, delta=0.05)  # aspect kept
                self.assertTrue(seen)
                self.assertTrue(await t.make_thumbnail(out, os.path.join(d, "t.jpg")))
            finally:
                shutil.rmtree(d, ignore_errors=True)
        asyncio.run(go())


class SplitTests(unittest.TestCase):
    def test_names_and_seconds(self):
        self.assertEqual(t.part_name("Movie.4K.mkv", 2), "Movie.4K.part02.mkv")
        self.assertEqual(t.part_name("a.zip", 3, video=False), "a.zip.003")
        self.assertEqual(quality.extract_quality(t.part_name("Movie.4K.mkv", 2)), "4K")
        # 5 GB, 100 min, 1.9 GB parts -> about 38 min each
        self.assertEqual(t.split_segment_seconds(5 * 1024**3, 6000, int(1.9 * 1024**3)), int(6000 * 1.9 * 0.92 / 5))
        self.assertEqual(t.split_segment_seconds(0, 10, 100), 0)

    def test_split_raw_roundtrip(self):
        d = tempfile.mkdtemp()
        try:
            src = os.path.join(d, "big.bin")
            data = os.urandom(2_500_000)
            open(src, "wb").write(data)
            parts = t.split_raw(src, os.path.join(d, "o"), 1_000_000, "big.bin")
            self.assertEqual([os.path.basename(p) for p in parts], ["big.bin.001", "big.bin.002", "big.bin.003"])
            self.assertEqual([os.path.getsize(p) for p in parts], [1_000_000, 1_000_000, 500_000])
            self.assertEqual(b"".join(open(p, "rb").read() for p in parts), data)
        finally:
            shutil.rmtree(d, ignore_errors=True)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class SplitFfmpegTest(unittest.TestCase):
    def test_split_video_parts_play_and_fit(self):
        async def go():
            d = tempfile.mkdtemp()
            try:
                src = os.path.join(d, "v.mkv")
                p = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=40",
                    "-f", "lavfi", "-i", "sine=duration=40", "-c:v", "libx264", "-g", "25", "-b:v", "400k", "-c:a", "aac", src)
                await p.wait()
                size = os.path.getsize(src)
                limit = size // 3
                parts = await t.split_video(src, os.path.join(d, "p"), 40.0, limit, hard_limit=limit)
                self.assertGreaterEqual(len(parts), 3)
                self.assertTrue(all(os.path.getsize(x) <= limit for x in parts))
                total = 0.0
                for x in parts:
                    info = await t.probe(x)
                    self.assertEqual(info["width"], 640)       # each part is a real, playable video
                    total += info["duration"]
                self.assertAlmostEqual(total, 40.0, delta=2.0)
            finally:
                shutil.rmtree(d, ignore_errors=True)
        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()


class UpscaleTests(unittest.TestCase):
    def test_upscale_targets(self):
        up = ["1080p", "1440p", "4K"]
        self.assertEqual(t.pick_upscale_targets(1280, 720, up), ["1080p", "1440p", "4K"])
        self.assertEqual(t.pick_upscale_targets(1920, 1080, up), ["1440p", "4K"])
        self.assertEqual(t.pick_upscale_targets(3840, 2160, up), [])
        self.assertEqual(t.pick_upscale_targets(256, 144, up), [])               # 4K would be 15x: refused
        self.assertEqual(t.pick_upscale_targets(1280, 720, up, have={"1080p"}), ["1440p", "4K"])
        self.assertEqual(t.pick_upscale_targets(1280, 720, []), [])

    def test_upscale_name_and_cmd(self):
        n = t.output_name("Show.S01E01.720p.mkv", "4K", "Upscaled")
        self.assertEqual(n, "Show.S01E01.4K.Upscaled.mp4")
        self.assertEqual(quality.extract_quality(n), "4K")
        c = " ".join(t.build_upscale_cmd("a.mkv", "b.mp4", "4K"))
        for needle in ("lanczos", "hqdn3d", "cas=0.6", "unsharp", "libx264", "w=3840:h=2160"):
            self.assertIn(needle, c)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class UpscaleFfmpegTest(unittest.TestCase):
    def test_real_upscale(self):
        async def go():
            d = tempfile.mkdtemp()
            try:
                src = os.path.join(d, "s.mp4")
                p = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x272:rate=24:duration=2", src)
                await p.wait()
                out = os.path.join(d, "o.mp4")
                rc, err = await t.run_ffmpeg(t.build_upscale_cmd(src, out, "1080p", False, "ultrafast"), 2.0)
                self.assertEqual(rc, 0, err)
                o = await t.probe(out)
                self.assertEqual(o["width"], 1920)
                self.assertEqual(o["width"] % 2 + o["height"] % 2, 0)
                self.assertAlmostEqual(o["width"] / o["height"], 640 / 272, delta=0.05)
            finally:
                shutil.rmtree(d, ignore_errors=True)
        asyncio.run(go())
