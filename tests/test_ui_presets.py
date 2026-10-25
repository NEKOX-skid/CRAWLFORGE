import threading, unittest
from crawlforge.web import make_server

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # browser test is optional
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "playwright not installed")
class PresetIndependence(unittest.TestCase):
    def test_presets_do_not_leak_into_each_other(self):
        web, tok = make_server("127.0.0.1", 0); threading.Thread(target=web.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                b = p.chromium.launch(); pg = b.new_page(); pg.goto(f"http://127.0.0.1:{web.server_port}/?t={tok}")
                pg.wait_for_selector('#presets .chip:text-is("stealth")')
                pg.click('#presets .chip:text-is("stealth")'); self.assertEqual(pg.input_value("#concurrency"), "2")
                pg.click('#presets .chip:text-is("api-hunt")'); self.assertIn("json", pg.input_value("#ext_match")); self.assertEqual(pg.input_value("#strategy"), "breadth-first")
                pg.click('#presets .chip:text-is("standard")')
                self.assertEqual(pg.input_value("#concurrency"), "10"); self.assertEqual(pg.input_value("#rate_limit"), "150")
                self.assertEqual(pg.input_value("#ext_match"), ""); self.assertEqual(pg.input_value("#strategy"), "depth-first"); self.assertEqual(pg.input_value("#delay"), "0")
                b.close()
        finally:
            web.shutdown(); web.server_close()

if __name__ == "__main__":
    unittest.main()
