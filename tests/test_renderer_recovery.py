"""Own module: the render tests keep one browser open, and a second one in the same thread would clash."""


def test_a_failed_browser_launch_never_poisons_the_next_one(monkeypatch):
    from hunter import render

    real = render.sync_playwright
    fails = {"n": 1}

    def flaky():
        pw = real()

        class Starter:
            def start(self):
                started = pw.start()
                launch = started.chromium.launch

                def launch_once(*a, **kw):
                    if fails["n"]:
                        fails["n"] -= 1
                        raise RuntimeError("Executable doesn't exist (simulated)")
                    return launch(*a, **kw)
                monkeypatch.setattr(started.chromium, "launch", launch_once)
                return started
        return Starter()

    monkeypatch.setattr(render, "sync_playwright", flaky)
    monkeypatch.setattr(render.subprocess, "run", lambda *a, **kw: None)  # no real reinstall in tests
    monkeypatch.setattr(render.time, "sleep", lambda s: None)
    with render.Renderer() as r:  # first launch fails, the retry works
        assert r._browser.is_connected()
    with render.Renderer() as r:  # and the next run in the same process is fine
        assert r._browser.is_connected()
