import asyncio

from app import main


async def test_failed_background_task_exits_process(monkeypatch, caplog):
    codes = []
    monkeypatch.setattr(main.os, "_exit", codes.append)

    async def boom():
        raise RuntimeError("boom")

    task = asyncio.create_task(boom())
    await asyncio.gather(task, return_exceptions=True)
    main.on_task_done(task)
    assert codes == [1]
    assert "boom" in caplog.text


async def test_cancelled_background_task_does_not_exit(monkeypatch):
    codes = []
    monkeypatch.setattr(main.os, "_exit", codes.append)
    task = asyncio.create_task(asyncio.sleep(10))
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    main.on_task_done(task)
    assert codes == []


async def test_widget_updates_registered_only_when_enabled(monkeypatch):
    from app.config import Settings

    async def idle(*args):
        await asyncio.sleep(3600)

    for name in ("run_mqtt", "prune_loop", "run_scheduler", "run_widget_updates"):
        monkeypatch.setattr(main, name, idle)

    def tasks_for(**kwargs):
        settings = Settings(bot_token="x", **kwargs)
        tasks = main.background_tasks(None, settings, None, None)
        for t in tasks:
            t.cancel()
        return tasks

    assert len(tasks_for(widgets_enabled=True)) == 4
    assert len(tasks_for(widgets_enabled=False)) == 3
