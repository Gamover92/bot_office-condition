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
